"""doc_sender: the single source of truth for safe Telegram document delivery.

Born from the 2026-06-22 morning failure -- both the chat brain and the
tool-less /claude FAKED sending a file -- and hardened by the same day's
adversarial review (11 findings). These tests pin the guarantees:
  * resolve_sendable jails to a whitelist + a git-ignore PRIVACY gate (no
    secrets / private funding docs / traversal / outside-repo / oversize),
  * detect_file_request catches real "send me X" (incl. natural Polish verbs and
    diacritics) without hijacking ordinary chat.
"""

from pathlib import Path

import pytest

from agent_core.telegram import doc_sender
from agent_core.telegram.doc_sender import resolve_sendable, detect_file_request

_REPO = Path(doc_sender.__file__).resolve().parents[2]


@pytest.fixture
def fake_repo(tmp_path, monkeypatch):
    """A tmp 'repo' with the git-ignore privacy gate stubbed open, so we can test
    the whitelist/denylist/size/symlink logic in isolation."""
    monkeypatch.setattr(doc_sender, "_REPO_ROOT", tmp_path)
    monkeypatch.setattr(doc_sender, "_is_gitignored", lambda p: False)
    (tmp_path / "docs").mkdir()
    return tmp_path


# --- resolve_sendable: jail + privacy gate (against the REAL repo) ----------

def test_public_doc_resolves_to_absolute_path():
    r = resolve_sendable("docs/DIGITAL_HUMAN_ROADMAP.md")
    assert r.ok
    assert r.path == str(_REPO / "docs" / "DIGITAL_HUMAN_ROADMAP.md")


def test_allowed_toplevel_doc():
    r = resolve_sendable("README.md")
    assert r.ok and Path(r.path).name == "README.md"


@pytest.mark.parametrize("private", [
    "docs/funding/FUNDING_STRATEGY_MARIA.md",   # gitignored: NEVER publish (ADR-029)
    "docs/SESSION_LOG.md",                        # gitignored
    "docs/CODEX_TASKS.md",                        # gitignored
])
def test_gitignored_private_docs_blocked(private):
    """The headline review finding: whole-dir whitelist must NOT leak private IP."""
    if not (_REPO / private).exists():
        pytest.skip(f"{private} not present in this checkout")
    r = resolve_sendable(private)
    assert not r.ok and "prywatny" in r.reason


def test_claude_notes_not_in_whitelist():
    # claude_notes/ is private inter-session scratch -> not a sendable location.
    r = resolve_sendable("claude_notes/2026-06-22_morning_report.md")
    assert not r.ok


def test_empty_arg_rejected():
    assert not resolve_sendable("").ok
    assert not resolve_sendable("   ").ok


def test_env_secret_rejected_by_whitelist():
    assert not resolve_sendable(".env").ok


def test_parent_traversal_rejected():
    assert not resolve_sendable("../.env").ok
    assert not resolve_sendable("docs/../../etc/passwd").ok


def test_absolute_outside_repo_rejected():
    assert not resolve_sendable("/etc/passwd").ok


def test_meta_data_runtime_state_rejected():
    assert not resolve_sendable("meta_data/llm_tape.jsonl").ok


def test_nonexistent_file_in_allowed_dir_reports_not_found():
    r = resolve_sendable("docs/this_does_not_exist_xyz.md")
    assert not r.ok and "Nie znalazlem" in r.reason


def test_denylisted_name_inside_allowed_dir(fake_repo):
    (fake_repo / "docs" / "my_secret_token.md").write_text("x")
    (fake_repo / "docs" / "ok.md").write_text("hello")
    assert not resolve_sendable("docs/my_secret_token.md").ok
    assert resolve_sendable("docs/ok.md").ok


def test_oversize_and_empty_rejected(fake_repo):
    (fake_repo / "docs" / "empty.md").write_text("")
    (fake_repo / "docs" / "big.md").write_bytes(b"x" * (doc_sender._MAX_SEND_BYTES + 1))
    assert not resolve_sendable("docs/empty.md").ok
    assert not resolve_sendable("docs/big.md").ok


def test_symlink_escape_rejected(fake_repo):
    secret = fake_repo.parent / "outside_secret.txt"
    secret.write_text("TOP SECRET")
    link = fake_repo / "docs" / "link.md"
    try:
        link.symlink_to(secret)
    except OSError:
        pytest.skip("symlinks unsupported on this platform")
    # resolve() follows the link outside the repo -> containment rejects it.
    assert not resolve_sendable("docs/link.md").ok


def test_privacy_gate_fails_closed_on_git_error(fake_repo, monkeypatch):
    # If git cannot vet a file, it must be treated as private (blocked).
    (fake_repo / "docs" / "x.md").write_text("hi")
    monkeypatch.setattr(doc_sender, "_is_gitignored", lambda p: True)
    assert not resolve_sendable("docs/x.md").ok


# --- detect_file_request: intent without hijacking chat --------------------

def test_morning_failure_message_now_sends_dh_roadmap():
    """The exact message that failed on 2026-06-22 must now resolve to a SEND."""
    fr = detect_file_request("Mogę dostać mapę rozwoju digital human na telegram ?")
    assert fr is not None and fr.kind == "send"
    assert fr.path.endswith("docs/DIGITAL_HUMAN_ROADMAP.md")


@pytest.mark.parametrize("msg", [
    "wyślij mi proszę mapę rozwoju Mari digital Human na telegram",
    "prześlij changelog",
    "wyslij docs/ROADMAP.md",
    "poslij mi roadmap digital human na telegram",   # r1[3]: natural verb
    "daj mi mape rozwoju",                            # r1[3]
    "wyślij mi mapę rozwoju",                          # r1[9]: diacritics
    "wrzuc mi plik docs/ROADMAP.md",
    # round-2 findings: modal+infinitive (the polite Polish request form) [r2-1]
    "Mozesz mi wyslac roadmape na telegramie?",
    "Moglbys przeslac plik docs/ROADMAP.md?",
    "prosze przeslac dokumentacje digital human",
    "wyslij architekture",                            # r2-5: stem match (accusative)
    "wyslij kontrakty",
])
def test_clear_send_requests(msg):
    fr = detect_file_request(msg)
    assert fr is not None and fr.kind == "send" and fr.path


@pytest.mark.parametrize("msg", [
    "co teraz robisz?",
    "jak się masz Mario?",
    "opowiedz mi o swoim rozwoju",
    "wyślij mi szczegóły jak poszło",                 # strong cue, no doc target
    "poprawmy docs/ROADMAP.md o nową sekcję",          # path but NO delivery cue
    # r1[2]: weak receive + bare topical word must NOT be a file request
    "chce dostac twoja opinie o roadmapie",
    "dostane jakis pomysl na changelog do projektu?",
    "kiedy dostane odpowiedz o architekturze systemu?",
    # r1[8]: past-tense mention of a path in discussion must NOT trigger
    "wyslalam ci uwagi do docs/ROADMAP.md wczoraj, co o nich myslisz?",
    # r2-2: future declarative "I'll send you..." is a statement, NOT a request
    "wysle ci plik wieczorem",
    "Wysle ci mape rozwoju projektu",
    "Eryk wysle ci ten plik jutro",
    # r2-3: idioms with a doc noun must not be hijacked
    "rzuc mi okiem na ten dokument prosze",
    "pokaz mi co zawiera ten dokument",
    "daj mi znac ktory dokument wybrac",
    # r2-4: directional imperatives (action AWAY from the speaker)
    "Wrzuc plik do kosza prosze",
    "Przekaz dokumenty do ksiegowosci",
    # declaration with a known-doc topic ("I must send X to the boss")
    "musze wyslac changelog do szefa",
    "",
])
def test_ordinary_chat_not_hijacked(msg):
    assert detect_file_request(msg) is None


def test_delivery_cue_unmappable_doc_redirects_not_confabulates():
    fr = detect_file_request("wyślij mi ten plik")
    assert fr is not None and fr.kind == "redirect"
    assert "/wyslij" in fr.message


def test_request_for_secret_never_sends():
    for msg in ("wyślij mi plik .env z sekretami",
                "wyslij docs/funding/FUNDING_STRATEGY_MARIA.md"):
        fr = detect_file_request(msg)
        assert fr is None or fr.kind == "redirect"   # never a SEND
        if fr is not None:
            assert fr.path is None
