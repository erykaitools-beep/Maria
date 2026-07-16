"""Etap 2 (DH 'Obecnosc'): plain (non-slash) Telegram text becomes real chat --
routed to Maria's brain -- instead of being silently dropped. Slash commands and
OperatorModel learning must stay untouched; failures degrade to a 'busy' line,
never a silent void nor a poll-loop crash. Flag-gated OFF (TELEGRAM_CHAT_ENABLED).
"""

from types import SimpleNamespace

from agent_core.telegram import TelegramBridge
from agent_core.modules.homeostasis_telegram_commands import (
    register_telegram_commands,
)


class _FakeBot:
    def __init__(self, updates, chat_id=12345):
        self._updates = updates
        self._chat_id = chat_id
        self.configured = True
        self.sent = []

    def get_updates(self):
        return self._updates

    def send_message(self, text, *a, **k):
        self.sent.append(text)


def _msg(text, chat_id=12345):
    return {"chat_id": chat_id, "text": text}


def _bridge(updates):
    bot = _FakeBot(updates)
    return TelegramBridge(bot=bot), bot


# --- bridge dispatch behaviour ------------------------------------------------

def test_plain_text_no_handler_no_reply_but_learned():
    """Default command-console: free-text consumed for learning, no reply."""
    bridge, bot = _bridge([_msg("co u ciebie slychac?")])
    unhandled = bridge.poll_and_respond()
    assert bot.sent == []                                  # no reply
    assert bridge.last_poll_texts == ["co u ciebie slychac?"]  # still learned
    assert len(unhandled) == 1


def _join(bridge):
    """Chat replies run on a detached thread; wait for it in tests."""
    if bridge._last_chat_thread is not None:
        bridge._last_chat_thread.join(timeout=5)


def test_plain_text_with_handler_routes_to_chat():
    bridge, bot = _bridge([_msg("opowiedz mi o sobie")])
    seen = []

    def handler(t):
        seen.append(t)
        return "Czesc, jestem Maria."

    bridge.set_chat_handler(handler)
    bridge.poll_and_respond()
    _join(bridge)
    assert seen == ["opowiedz mi o sobie"]                 # handler got the text
    assert bot.sent == ["Czesc, jestem Maria."]            # reply delivered
    assert bridge.last_poll_texts == ["opowiedz mi o sobie"]  # learning preserved


def test_document_caption_does_not_route_to_chat():
    bot = _FakeBot([{
        "chat_id": 12345,
        "text": "spojrz na to",
        "document": {"file_id": "abc", "file_name": "x.exe"},  # disallowed ext
    }])
    bridge = TelegramBridge(bot=bot)
    seen = []
    bridge.set_chat_handler(lambda t: seen.append(t) or "reply")
    bridge.poll_and_respond()
    _join(bridge)
    assert seen == []                          # chat never sees a document caption
    assert bridge._last_chat_thread is None    # no chat thread dispatched


def test_slash_command_never_hits_chat_handler():
    bridge, bot = _bridge([_msg("/status")])
    bridge.register_command("status", lambda a: "STATUS OK")
    bridge.set_chat_handler(lambda t: "CHAT (should not run)")
    bridge.poll_and_respond()
    assert bot.sent == ["STATUS OK"]                       # routed to the command
    assert bridge.last_poll_texts == []                    # handled, not free-text


def test_unknown_slash_warns_not_chat():
    bridge, bot = _bridge([_msg("/nosuch")])
    bridge.set_chat_handler(lambda t: "CHAT (should not run)")
    bridge.poll_and_respond()
    assert len(bot.sent) == 1
    assert "Nieznana komenda" in bot.sent[0]               # warn, not chat


def test_empty_reply_degrades_to_busy():
    bridge, bot = _bridge([_msg("hej")])
    bridge.set_chat_handler(lambda t: None)                # brain returned nothing
    bridge.poll_and_respond()
    _join(bridge)
    assert len(bot.sent) == 1
    assert "zajeta" in bot.sent[0].lower()


def test_handler_exception_degrades_not_crash():
    bridge, bot = _bridge([_msg("hej"), _msg("/status")])
    bridge.register_command("status", lambda a: "STATUS OK")

    def boom(t):
        raise RuntimeError("brain exploded")

    bridge.set_chat_handler(boom)
    bridge.poll_and_respond()                              # must NOT raise
    _join(bridge)
    assert any("zajeta" in s.lower() for s in bot.sent)    # busy line for chat msg
    assert "STATUS OK" in bot.sent                         # later command survived


def test_chat_reply_does_not_block_poll_loop():
    """The poll loop must return BEFORE a slow brain reply finishes -- otherwise
    the tick's is_alive guard suppresses all later command intake (review [1])."""
    import threading as _t
    started = _t.Event()
    release = _t.Event()

    def slow(_text):
        started.set()
        release.wait(5)            # simulate a cold-CPU reply
        return "spoznione"

    bridge, bot = _bridge([_msg("hej")])
    bridge.set_chat_handler(slow)
    bridge.poll_and_respond()      # returns immediately, reply still in flight
    assert started.wait(5)         # worker did start
    assert bot.sent == []          # ...but nothing sent yet -> loop wasn't blocked
    release.set()
    _join(bridge)
    assert bot.sent == ["spoznione"]


# --- registration wiring (homeostasis_telegram_commands) ----------------------

class _RegBridge:
    def __init__(self):
        self.handlers = {}
        self.chat_handler = None
        self.bot = SimpleNamespace(send_message=lambda *a, **k: None)

    def register_command(self, c, h):
        self.handlers[c] = h

    def set_chat_handler(self, h):
        self.chat_handler = h


class _Ctx:
    def __init__(self, **kw):
        self.__dict__.update(kw)

    def __getattr__(self, name):  # only on miss
        return None


def test_chat_handler_installed_only_when_flag_on(monkeypatch):
    monkeypatch.delenv("TELEGRAM_CHAT_ENABLED", raising=False)
    off = _RegBridge()
    register_telegram_commands(off, _Ctx())
    assert off.chat_handler is None                        # OFF -> command console

    monkeypatch.setenv("TELEGRAM_CHAT_ENABLED", "true")
    on = _RegBridge()
    register_telegram_commands(on, _Ctx())
    assert on.chat_handler is not None                     # ON -> chat installed


def test_chat_reply_uses_brain_and_handles_timeout(monkeypatch):
    from models.ollama_brain import BrainTimeout
    monkeypatch.setenv("TELEGRAM_CHAT_ENABLED", "1")

    class _Brain:
        def __init__(self, behavior):
            self.behavior = behavior

        def think(self, text, raise_on_timeout=False):
            if self.behavior == "ok":
                return "Odpowiedz Marii"
            if self.behavior == "timeout":
                raise BrainTimeout("stall")
            return ""  # empty

    ok = _RegBridge()
    register_telegram_commands(ok, _Ctx(brain=_Brain("ok")))
    assert ok.chat_handler("hej") == "Odpowiedz Marii"

    to = _RegBridge()
    register_telegram_commands(to, _Ctx(brain=_Brain("timeout")))
    assert "zajeta" in to.chat_handler("hej").lower()      # graceful busy

    empty = _RegBridge()
    register_telegram_commands(empty, _Ctx(brain=_Brain("empty")))
    assert empty.chat_handler("hej") is None               # bridge then sends busy

    nobrain = _RegBridge()
    register_telegram_commands(nobrain, _Ctx(brain=None))
    assert nobrain.chat_handler("hej") is None             # no brain -> no reply
