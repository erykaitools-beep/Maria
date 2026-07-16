"""Safe, whitelisted delivery of repository documents over Telegram.

The morning of 2026-06-22 exposed a gap: asked to "send me the roadmap on
Telegram", both Maria's chat brain (confabulated success -- "przesylam plik...")
and the tool-less /claude backend (emitted hallucinated <tool_call> text marked
COMPLETED) FAKED success, because neither could perform an action -- only produce
text. The bot itself can already send a document (TelegramBot.send_document);
what was missing was a path that turns a request into a real, safe send.

This module is that single source of truth. It is READ-ONLY: it never sends and
never writes -- it only (a) resolves a path / known-doc name to a safe, existing,
sendable file, and (b) classifies whether a free-text message is a "send me a
file" request. The actual send (bot.send_document) stays with the caller -- the
/wyslij command, the /claude short-circuit, and the chat intercept all share THIS
one jail + privacy gate + known-doc map, so they cannot drift apart.

Safety model (an outward-facing send must be safe-by-default):
  * Location whitelist: only files under docs/ (plus a few explicit top-level
    docs) are reachable. claude_notes/, meta_data/, venv/, .git, the market repo
    -- none are in the whitelist.
  * Privacy gate (the important one): a file is sendable ONLY if git does NOT
    ignore it. .gitignore is the project's source of truth for "private, NEVER
    publish (ADR-029)" -- it covers docs/funding/*, docs/incoming/*, the session
    logs, CODEX_TASKS.md and all of claude_notes/. Fails CLOSED: if git cannot be
    consulted, the file is treated as private and refused.
  * Path.resolve() collapses symlinks and "..", so a symlink/traversal escaping
    the repo is rejected by the containment check.
  * A belt-and-braces denylist drops obviously secret-ish names; 20 MiB cap;
    empty files rejected.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import NamedTuple, Optional

# .../agent_core/telegram/doc_sender.py -> parents[2] == repo root
_REPO_ROOT = Path(__file__).resolve().parents[2]

# Only files under these repo-relative directories may be sent. claude_notes/ is
# deliberately absent: it is entirely gitignored (private inter-session notes).
_ALLOWED_DIRS = ("docs",)
# ...plus these explicit top-level files (no other top-level file is sendable).
_ALLOWED_TOPLEVEL = frozenset({"README.md", "CLAUDE.md", "CHANGELOG.md",
                               "CONTRIBUTING.md", "DEVELOPER_GUIDE.md"})
_MAX_SEND_BYTES = 20 * 1024 * 1024

# Belt-and-braces: never send obviously secret-ish files even if whitelisted.
_DENY_SUFFIXES = (".key", ".pem", ".pfx", ".p12", ".crt", ".pyc")
_DENY_NAME_SUBSTR = ("secret", "token", "password", "credential", "apikey",
                     "api_key", ".env")


class Resolved(NamedTuple):
    ok: bool
    path: Optional[str]   # absolute path when ok
    reason: str           # human-readable reason when not ok (else "")


def _err(msg: str) -> "Resolved":
    return Resolved(ok=False, path=None, reason=msg)


def _allowed_hint() -> str:
    return ("Moge wyslac tylko publiczne dokumenty z: " + ", ".join(_ALLOWED_DIRS)
            + " (lub pliki: " + ", ".join(sorted(_ALLOWED_TOPLEVEL)) + ").")


def _is_gitignored(abs_path: str) -> bool:
    """True if git marks the path as ignored -> private per ADR-029, never send.

    .gitignore is the project's source of truth for "private / NEVER publish":
    docs/funding/*, docs/incoming/*, docs/SESSION_LOG.md, CODEX_TASKS.md, all of
    claude_notes/, etc. Fails CLOSED -- any git error means "cannot vet" -> treat
    as private and refuse, so a doc we cannot check is never leaked.
    """
    try:
        r = subprocess.run(
            ["git", "-C", str(_REPO_ROOT), "check-ignore", "-q", abs_path],
            capture_output=True, timeout=5,
        )
    except Exception:
        return True   # git unavailable / not a repo -> safe-by-default: block
    if r.returncode == 0:
        return True    # ignored == private
    if r.returncode == 1:
        return False   # not ignored == public/shareable
    return True        # 128 / other error -> block


def resolve_sendable(raw: str) -> Resolved:
    """Resolve a path / repo-relative path to a safe, sendable file.

    Returns Resolved(ok=True, path=<abs>) or Resolved(ok=False, reason=<why>).
    Read-only and side-effect free (a git check-ignore subprocess, no writes).
    """
    raw = (raw or "").strip().strip('"').strip("'").strip()
    if not raw:
        return _err("Podaj sciezke, np. docs/DIGITAL_HUMAN_ROADMAP.md")
    # Path("/repo") / "/abs" == Path("/abs"), so an absolute path under the repo
    # still resolves correctly; anything else is anchored at the repo root.
    try:
        candidate = (_REPO_ROOT / raw).resolve()
    except (OSError, ValueError, RuntimeError) as exc:
        return _err(f"Niepoprawna sciezka: {exc}")
    # Containment: must live inside the repo (a symlink/.. escape collapses here).
    try:
        rel = candidate.relative_to(_REPO_ROOT)
    except ValueError:
        return _err("Sciezka poza repozytorium.")
    parts = rel.parts
    in_allowed_dir = bool(parts) and parts[0] in _ALLOWED_DIRS
    is_allowed_top = len(parts) == 1 and parts[0] in _ALLOWED_TOPLEVEL
    if not (in_allowed_dir or is_allowed_top):
        return _err(_allowed_hint())
    name_low = candidate.name.lower()
    if candidate.suffix.lower() in _DENY_SUFFIXES or any(
        s in name_low for s in _DENY_NAME_SUBSTR
    ):
        return _err("Ten plik jest na liscie odmowy (moze zawierac sekrety).")
    if candidate.is_symlink():  # explicit, though resolve() already followed it
        return _err("Sciezka jest dowiazaniem symbolicznym (odrzucone).")
    if not candidate.exists() or not candidate.is_file():
        return _err(f"Nie znalazlem pliku: {rel}")
    try:
        size = candidate.stat().st_size
    except OSError as exc:
        return _err(f"Nie moge odczytac pliku: {exc}")
    if size == 0:
        return _err(f"Plik jest pusty: {rel}")
    if size > _MAX_SEND_BYTES:
        return _err("Plik za duzy (limit 20 MiB).")
    # Privacy gate LAST (it spawns git): only public (non-ignored) docs leave disk.
    if _is_gitignored(str(candidate)):
        return _err("Plik jest prywatny (gitignored) - nie wysylam (ADR-029).")
    return Resolved(ok=True, path=str(candidate), reason="")


# --- free-text "send me a file" intent ------------------------------------

# Known docs by phrase, so a conversational request with no path still resolves.
# Order matters: most specific first (DH before generic "roadmap"/"mapa rozwoju").
# Matched against diacritic-FOLDED, lowercased text (see _fold). Phrases are
# STEMS (no trailing inflectional vowel) so the accusative used after an
# imperative matches too: "architektur" catches architektura/architekture/
# architekturę; "rozwoj" catches rozwoju/rozwoj.
_KNOWN_DOCS = (
    (("digital human", "digital-human", "dh roadmap", "rozwoj digital",
      "digitalnego czlowieka"),
     "docs/DIGITAL_HUMAN_ROADMAP.md"),
    (("roadmap", "mapa rozwoj", "mape rozwoj", "mapy rozwoj", "plan rozwoj",
      "fazy rozwoj"), "docs/ROADMAP.md"),
    (("architektur", "architecture", "diagram warstw"),
     "docs/ARCHITECTURE.md"),
    (("kontrakt", "contracts"), "docs/CONTRACTS.md"),
    (("changelog", "historia zmian"), "docs/CHANGELOG.md"),
    (("model registry", "rejestr modeli", "lista modeli"),
     "docs/MODEL_REGISTRY.md"),
)

# STRONG cue: an unambiguous request to RECEIVE a file. Built to dodge the
# false positives the 2026-06-22 review found:
#   * future declarative "wysle/wysle ci" (a statement, not a request) -> the
#     bare "e\b"/"emy" endings are NOT used; only imperative "-ij", 2sg-future
#     "-esz", and a modal+infinitive frame count.
#   * directional verbs "wrzuc/przekaz X do kosza" (action AWAY) -> only count
#     when aimed at the speaker ("... mi ...").
#   * idioms "rzuc mi okiem", "pokaz mi co zawiera", "daj mi znac" -> "rzuc mi"
#     and "pokaz mi" dropped entirely; "daj mi" excludes the common idioms.
# Past tense ("wyslalam ci...") stays excluded (no -al/-ala ending matches).
_SEND_IMPERATIVE = (
    r"wy[sś]lij|prze[sś]lij|po[sś]lij|pode[sś]lij|ze[sś]lij|nade[sś]lij|"
    r"wy[sś]lijcie|prze[sś]lijcie|"
    r"wy[sś]lesz|prze[sś]lesz|po[sś]lesz|"          # 2sg future = request question
    r"udost[eę]pnij|[sś]ci[aą]gnij|pobierz|wyeksportuj|wyexportuj"
)
_SEND_TO_ME = r"wrzu[cć]\s+mi|przeka[zż]\s+mi"      # directional: require "mi"
_GIVE_ME = (                                         # "daj mi <X>" minus idioms
    r"daj\s+mi\s+(?!zna[cć]\b|spok|chwil|czas|sygna|rad[eę]\b|wybor|szans|wymowk)"
)
_MODAL_INF = (                                        # "mozesz mi wyslac ...", etc.
    r"(?:mo[zż]esz|m[oó]g[lł]by[sś]|m[oó]g[lł]aby[sś]|prosz[eę]|czy\s+mo[zż]\w*)"
    r"[^.?!\n]{0,40}"
    r"(?:wy[sś][lł]a[cć]|prze[sś][lł]a[cć]|po[sś][lł]a[cć]|pode[sś][lł]a[cć]|"
    r"udost[eę]pni[cć]|przekaza[cć])"
)
_STRONG_CUE = re.compile(
    "(" + "|".join((_SEND_IMPERATIVE, _SEND_TO_ME, _GIVE_ME, _MODAL_INF)) + ")",
    re.IGNORECASE,
)
# WEAK cue: a receive phrasing ("can I get", "I'd like to receive"). Ambiguous on
# its own -- counts as delivery intent only with concrete file context (below).
_WEAK_CUE = re.compile(
    r"(mog[eę]\s+dosta|chc[eę]\s+dosta|popros|dostan|dosta[cć])",
    re.IGNORECASE,
)
# A concrete document/file noun. Deliberately narrow: bare topical words
# (roadmap/changelog/architektura) are NOT here -- they live only in _KNOWN_DOCS
# and require real intent, so "co u changeloga?" is not a file request.
_DOC_NOUN = re.compile(
    r"(\bplik\w*|\bdokument\w*|\.md\b|\.pdf\b|\bpdf\b|map[ęea]\s+rozwoj\w*)",
    re.IGNORECASE,
)
# An explicit repo-relative path token anywhere in the message.
_PATH_TOKEN = re.compile(r"((?:docs|claude_notes)/[\w./\-]+\.\w+)", re.IGNORECASE)

_REDIRECT_HINT = (
    "Nie wysylam plikow sama z czatu i nie zgaduje ktory plik. "
    "Podaj sciezke komenda /wyslij <sciezka>, np. "
    "/wyslij docs/DIGITAL_HUMAN_ROADMAP.md."
)

_PL_FOLD = str.maketrans("ąćęłńóśźż", "acelnoszz")


def _fold(s: str) -> str:
    """Drop Polish diacritics so ASCII _KNOWN_DOCS phrases match 'mapę rozwoju'."""
    return s.translate(_PL_FOLD)


class FileRequest(NamedTuple):
    kind: str               # "send" or "redirect"
    path: Optional[str]     # absolute path when kind == "send"
    message: str            # confirmation (send) or honest guidance (redirect)


def _match_known_doc(folded_low: str) -> Optional[str]:
    for phrases, rel in _KNOWN_DOCS:
        if any(p in folded_low for p in phrases):
            return rel
    return None


def detect_file_request(text: str) -> Optional[FileRequest]:
    """Classify a free-text message as a file-delivery request.

    Returns:
      * FileRequest("send", path=<abs>, message=<confirm>) when the message
        clearly asks to receive a doc we can map to a safe, existing file.
      * FileRequest("redirect", None, message=<guidance>) when it clearly asks
        for a file we cannot map -> honest "use /wyslij <path>" instead of a
        confabulated "I sent it".
      * None when it is not a file-delivery request -> normal chat.

    Conservative by design. Delivery intent = a STRONG imperative send verb, OR a
    WEAK receive phrasing combined with concrete file context (a doc noun, an
    explicit path, or "telegram"). A weak phrasing around a bare topical word
    ("chce dostac opinie o roadmapie") is NOT a file request -> normal chat.
    """
    if not text:
        return None
    low = text.lower()
    folded = _fold(low)

    strong = bool(_STRONG_CUE.search(low))
    weak = bool(_WEAK_CUE.search(low))
    has_doc_noun = bool(_DOC_NOUN.search(low))
    has_telegram = "telegram" in low
    explicit = _PATH_TOKEN.search(text)
    known_rel = _match_known_doc(folded)

    has_intent = strong or (weak and (has_doc_noun or has_telegram or bool(explicit)))
    if not has_intent:
        return None  # ordinary chat (incl. weak receive of a bare topical word)

    # 1) Explicit repo path -> send if safe, else honest redirect (with reason).
    if explicit:
        token = explicit.group(1)
        res = resolve_sendable(token)
        if res.ok:
            return FileRequest("send", res.path, f"Dokument: {Path(token).name}")
        return FileRequest("redirect", None, f"{res.reason} Uzyj: /wyslij <sciezka>.")

    # 2) A doc we recognise by name/phrase -> real send (else honest redirect).
    if known_rel:
        res = resolve_sendable(known_rel)
        if res.ok:
            return FileRequest("send", res.path, f"Dokument: {Path(known_rel).name}")
        return FileRequest(
            "redirect", None,
            f"{res.reason} Mozesz tez podac sciezke: /wyslij <sciezka>.",
        )

    # 3) Clearly a file request (doc noun) but unmapped -> honest redirect.
    if has_doc_noun:
        return FileRequest("redirect", None, _REDIRECT_HINT)

    # Strong cue but no document target at all (e.g. "pokaz mi co teraz robisz")
    # -> normal chat, not a file request.
    return None
