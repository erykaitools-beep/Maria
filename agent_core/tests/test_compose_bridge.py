"""compose_bridge: "napisz X i wyslij jako plik" -> a REAL file, not a phantom.

Born from the 2026-06-22 critical test where Maria invented
`/wyslij docs/MARIA_LIST_ZYCZEN.txt` (a file she never wrote). Pins: compose
intent detection, phantom-/wyslij stripping (honesty), and real write+send.
"""

from unittest.mock import MagicMock

import pytest

from agent_core.telegram import compose_bridge as cb
from agent_core.telegram.compose_bridge import (
    is_compose_request,
    strip_phantom_wyslij,
    maybe_deliver_compose,
)


# --- is_compose_request -----------------------------------------------------

@pytest.mark.parametrize("msg", [
    "Maria mozesz napisac do mnie list z lista zyczen. Wyslij mi przez telegram ten list",
    "przygotuj raport i zapisz do pliku",
    "napisz notatke o fizyce i wyslij mi ja",
    "stworz dokument z planem i przeslij na telegram",
])
def test_compose_requests_detected(msg):
    assert is_compose_request(msg) is True


@pytest.mark.parametrize("msg", [
    "co teraz robisz?",
    "wyslij mi mape rozwoju digital human",   # deliver, but no compose verb
    "napisz notatke o fizyce",                  # compose, but no deliver cue
    "jak sie masz?",
    "",
])
def test_non_compose_not_detected(msg):
    assert is_compose_request(msg) is False


# --- strip_phantom_wyslij ---------------------------------------------------

def test_strip_phantom_wyslij_removes_invented_file():
    reply = ("Oto lista zyczen:\n1. uczyc sie\n2. rosnac\n\n"
             "Wysylanie listu... /wyslij docs/MARIA_LIST_ZYCZEN.txt")
    out = strip_phantom_wyslij(reply)
    assert "/wyslij" not in out and "MARIA_LIST_ZYCZEN" not in out
    assert "lista zyczen" in out                      # the content survives


def test_strip_keeps_real_doc_reference():
    reply = "Mozesz pobrac mape: /wyslij docs/ROADMAP.md"
    # docs/ROADMAP.md really exists -> a valid reference, leave it
    assert strip_phantom_wyslij(reply) == reply


def test_strip_noop_without_wyslij():
    reply = "Zwykla odpowiedz bez komendy."
    assert strip_phantom_wyslij(reply) == reply


# --- maybe_deliver_compose --------------------------------------------------

@pytest.fixture
def compose_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(cb, "_COMPOSE_DIR", tmp_path / "maria_compose")
    return tmp_path / "maria_compose"


def test_compose_request_writes_and_sends_real_file(compose_dir):
    sent = []
    send = MagicMock(side_effect=lambda p, c: sent.append((p, c)) or True)
    reply = ("Oto Twoj list zyczen:\n1. uczyc sie sama\n2. miec rece\n\n"
             "/wyslij docs/MARIA_LIST_ZYCZEN.txt")     # phantom path
    out = maybe_deliver_compose(
        "napisz mi list i wyslij przez telegram", reply,
        send_document=send, now=123,
    )
    # a real file was written and sent
    assert send.call_count == 1
    written = compose_dir / "maria_123.txt"
    assert written.exists() and "uczyc sie sama" in written.read_text()
    # the chat reply confirms the real delivery and drops the phantom command
    assert "Zapisalam i wyslalam jako plik" in out
    assert "/wyslij" not in out


def test_non_compose_does_not_write_or_send(compose_dir):
    send = MagicMock(return_value=True)
    out = maybe_deliver_compose("co robisz?", "Pracuje nad nauka.",
                                send_document=send, now=1)
    send.assert_not_called()
    assert not compose_dir.exists()
    assert out == "Pracuje nad nauka."


def test_non_compose_still_strips_phantom(compose_dir):
    send = MagicMock(return_value=True)
    reply = "Jasne. /wyslij docs/NIE_MA_TAKIEGO.txt"
    out = maybe_deliver_compose("opowiedz mi cos", reply, send_document=send, now=1)
    send.assert_not_called()                 # not a compose request -> no delivery
    assert "/wyslij" not in out              # but the phantom is still cleaned


def test_send_failure_degrades_gracefully(compose_dir):
    send = MagicMock(return_value=False)
    out = maybe_deliver_compose(
        "napisz raport i zapisz do pliku",
        "Oto raport: wszystko dziala dobrze i stabilnie od rana.",
        send_document=send, now=9,
    )
    assert "powyzej" in out                  # content kept in chat
    assert send.call_count == 1


def test_thin_compose_reply_not_sent(compose_dir):
    send = MagicMock(return_value=True)
    out = maybe_deliver_compose("napisz i wyslij", "ok", send_document=send, now=1)
    send.assert_not_called()                 # < 20 chars -> nothing to deliver
