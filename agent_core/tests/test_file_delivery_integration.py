"""Integration: a Telegram chat "send me file X" must be fulfilled for real
(or honestly redirected), never confabulated.

2026-06-22 morning: asked "Mogę dostać mapę rozwoju digital human na telegram?",
Maria's chat brain replied "przesylam plik..." and sent nothing. Now the bridge
intercepts the request BEFORE the brain and either delivers the document or
points to /wyslij -- and the master prompt tells the brain not to fake sends.
"""

from agent_core.telegram import TelegramBridge
from agent_core.llm import master_prompt


class _FakeBot:
    def __init__(self, updates, chat_id=12345):
        self._updates = updates
        self._chat_id = chat_id
        self.configured = True
        self.sent = []
        self.docs = []

    def get_updates(self):
        return self._updates

    def send_message(self, text, *a, **k):
        self.sent.append(text)

    def send_document(self, file_path, caption=None, *a, **k):
        self.docs.append((file_path, caption))
        return True


def _msg(text, chat_id=12345):
    return {"chat_id": chat_id, "text": text}


def _join(bridge):
    for t in (bridge._last_file_thread, bridge._last_chat_thread):
        if t is not None:
            t.join(timeout=5)


def _bridge(updates):
    bot = _FakeBot(updates)
    bridge = TelegramBridge(bot=bot)
    return bridge, bot


# --- chat intercept ---------------------------------------------------------

def test_send_request_delivers_document_not_chat():
    bridge, bot = _bridge([_msg("Mogę dostać mapę rozwoju digital human na telegram?")])
    chat_seen = []
    bridge.set_chat_handler(lambda t: chat_seen.append(t) or "BRAIN (should not run)")
    bridge.poll_and_respond()
    _join(bridge)
    assert chat_seen == []                          # brain never asked to confabulate
    assert len(bot.docs) == 1                        # a real document was sent
    assert bot.docs[0][0].endswith("docs/DIGITAL_HUMAN_ROADMAP.md")


def test_unmappable_file_request_redirects_not_confabulates():
    bridge, bot = _bridge([_msg("wyślij mi ten plik")])
    chat_seen = []
    bridge.set_chat_handler(lambda t: chat_seen.append(t) or "BRAIN")
    bridge.poll_and_respond()
    _join(bridge)
    assert chat_seen == []                            # not routed to the brain
    assert bot.docs == []                             # nothing sent
    assert any("/wyslij" in m for m in bot.sent)      # honest guidance instead


def test_ordinary_chat_still_reaches_brain():
    bridge, bot = _bridge([_msg("co teraz robisz?")])
    chat_seen = []
    bridge.set_chat_handler(lambda t: chat_seen.append(t) or "Pracuje nad nauka.")
    bridge.poll_and_respond()
    _join(bridge)
    assert chat_seen == ["co teraz robisz?"]          # brain answered
    assert bot.docs == []                              # no file send
    assert bot.sent == ["Pracuje nad nauka."]


def test_no_chat_handler_means_no_file_intercept():
    """Flag OFF (no chat handler) -> historical silent-consume, no file send."""
    bridge, bot = _bridge([_msg("wyślij mi mapę rozwoju digital human")])
    bridge.poll_and_respond()
    _join(bridge)
    assert bot.docs == [] and bot.sent == []


# --- master prompt honesty --------------------------------------------------

def test_identity_states_file_send_limit_and_points_to_wyslij():
    identity = master_prompt._get_base_identity("Eryk")
    assert "/wyslij" in identity
    low = identity.lower()
    # honest file-handling: reply already reaches the operator + don't invent paths
    assert "nie wymyslaj sciezek" in low
    assert "juz trafia do operatora" in low
