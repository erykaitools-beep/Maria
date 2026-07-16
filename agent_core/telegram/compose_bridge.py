"""Bridge: a chat request to "write X and send it as a file" becomes a REAL file.

2026-06-22 critical test: "napisz mi list i wyslij przez telegram" -> Maria's
reply ended with `/wyslij docs/MARIA_LIST_ZYCZEN.txt`, a file she never wrote
(phantom). The content lived only in the chat text; nothing was delivered as a
file, and the command would have failed ("Nie znalazlem pliku").

This bridge closes it. When the OPERATOR'S message is a "compose + deliver as a
file" request, the brain's reply IS the composed content -> write it to a jailed
file and send it as a Telegram document for real. It also strips any phantom
`/wyslij <nonexistent>` Maria invents (honesty guard), so she can never again
point at a file that does not exist.

Side effects only: one jailed write (meta_data/maria_compose/, size-capped) + one
send via the injected send_document callable. No second LLM generation -- the
reply already IS the content.
"""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path
from typing import Callable, Optional

from agent_core.telegram.doc_sender import resolve_sendable, _fold

logger = logging.getLogger(__name__)

_COMPOSE_DIR = Path(__file__).resolve().parents[2] / "meta_data" / "maria_compose"
_MAX_COMPOSE_BYTES = 16 * 1024

# A COMPOSE request = a verb that asks Maria to author content...
_COMPOSE_VERB = re.compile(
    r"\b(napis|stworz|przygotuj|sporzadz|skomponuj|sformuluj|uloz|wygeneruj|"
    r"zrob\s+mi)\w*", re.IGNORECASE)
# ...AND a cue to deliver it as a file / over a channel (not just chat).
_DELIVER_CUE = re.compile(
    r"(wyslij|wysl\w*|przeslij|przesl\w*|zapis\w*|\bplik\w*|\bdokument\w*|"
    r"telegram|mail)", re.IGNORECASE)

_WYSLIJ_RE = re.compile(r"/wyslij\s+(\S+)")


def is_compose_request(text: str) -> bool:
    """True when the operator asks Maria to COMPOSE content AND deliver it as a
    file/message -- not an ordinary chat turn, not a request for an existing doc.
    Matched on diacritic-folded text so 'napisac'/'sporzadz' work with PL chars."""
    if not text:
        return False
    low = _fold(text.lower())
    return bool(_COMPOSE_VERB.search(low) and _DELIVER_CUE.search(low))


def _phantom_wyslij_path(reply: str) -> Optional[str]:
    """Return the path of a /wyslij directive whose target does NOT exist, else None."""
    m = _WYSLIJ_RE.search(reply or "")
    if not m:
        return None
    path = m.group(1).rstrip(".,;)”\"'")
    return None if resolve_sendable(path).ok else path


def strip_phantom_wyslij(reply: str) -> str:
    """Remove a `/wyslij <nonexistent>` Maria invented (it would only fail). A
    /wyslij pointing at a REAL doc is left untouched (the operator may run it)."""
    if not reply or _phantom_wyslij_path(reply) is None:
        return reply
    cleaned = re.sub(r"[^\n.!?]*?/wyslij\s+\S+[^\n.!?]*", "", reply)
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()


def maybe_deliver_compose(
    user_text: str,
    reply: str,
    *,
    send_document: Callable[[str, str], bool],
    now: Optional[float] = None,
) -> str:
    """Turn a compose-and-deliver request into a real file delivery.

    Always strips a phantom /wyslij from the reply. If the operator's message was
    a compose request, writes the reply body to a jailed file and sends it as a
    document. Returns the (possibly adjusted) chat reply. Never raises -- on any
    failure it degrades to the honesty-cleaned reply (content still in chat)."""
    if not reply:
        return reply
    body = strip_phantom_wyslij(reply)
    if not is_compose_request(user_text):
        return body  # ordinary turn -> just the phantom-cleaned reply
    if len(body.strip()) < 20:
        return body  # nothing substantial composed to deliver
    try:
        _COMPOSE_DIR.mkdir(parents=True, exist_ok=True)
        ts = int(now if now is not None else time.time())
        fpath = _COMPOSE_DIR / f"maria_{ts}.txt"
        fpath.write_text(body[:_MAX_COMPOSE_BYTES], encoding="utf-8")
        ok = bool(send_document(str(fpath), f"Dokument: {fpath.name}"))
    except Exception as e:
        logger.warning("[compose_bridge] deliver failed: %s", e)
        return body
    if ok:
        return body + f"\n\n(Zapisalam i wyslalam jako plik: {fpath.name}.)"
    return body + "\n\n(Tresc masz powyzej; wyslanie pliku sie nie powiodlo.)"
