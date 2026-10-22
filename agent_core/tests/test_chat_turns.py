"""Durable transport receipts: no replay after disconnect, crash, or content change."""
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest

from maria_ui.chat_turns import ChatTurnStore, TurnConflict


def test_restart_keeps_finished_reply_and_marks_inflight_unknown(tmp_path):
    store = ChatTurnStore(tmp_path / "turns")
    first, pending = uuid4().hex, uuid4().hex
    receipt = store.claim(first, "Przygotuj test w wybranym projekcie")
    assert receipt["new"] and receipt["interaction_id"] != first
    store.complete(first, {"success": True, "message": "Zlecenie przyjęte."})
    store.claim(pending, "Sprawdź wynik")
    restarted = ChatTurnStore(tmp_path / "turns")
    assert restarted.lookup(first)["response"]["message"] == "Zlecenie przyjęte."
    assert restarted.lookup(pending)["state"] == "unknown"
    assert restarted.claim(pending, "Sprawdź wynik")["new"] is False
    with pytest.raises(TurnConflict):
        restarted.claim(first, "Skasuj projekt")


def test_concurrent_duplicate_claims_get_one_server_identity(tmp_path):
    store = ChatTurnStore(tmp_path / "turns")
    nonce = uuid4().hex
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: store.claim(nonce, "Zleć jedno zadanie"), range(16)))
    assert sum(item["new"] for item in results) == 1
    assert store.lookup(nonce)["state"] == "pending"
    assert (store.path.stat().st_mode & 0o777) == 0o600


def test_evicted_replies_keep_dedup_tombstones(tmp_path):
    store = ChatTurnStore(tmp_path / "turns")
    first = uuid4().hex
    for nonce in [first] + [uuid4().hex for _ in range(500)]:
        store.claim(nonce, "test")
        store.complete(nonce, {"success": True, "message": "gotowe"})
    assert store.lookup(first)["state"] == "unknown"
    assert store.claim(first, "test")["new"] is False


def test_invalid_nonce_and_symlink_fail_closed(tmp_path):
    store = ChatTurnStore(tmp_path / "safe")
    for bad in [None, "../x", "x" * 32, "a" * 10000]:
        with pytest.raises(ValueError):
            store.claim(bad, "test")
    (tmp_path / "link").symlink_to(tmp_path / "safe", target_is_directory=True)
    with pytest.raises(ValueError):
        ChatTurnStore(tmp_path / "link")


def test_clear_forgets_response_without_reopening_old_dispatch(tmp_path):
    store = ChatTurnStore(tmp_path / "turns")
    nonce = uuid4().hex
    store.claim(nonce, "test")
    store.complete(nonce, {"success": True, "message": "private conversation"})
    store.forget_responses()
    assert "response" not in store.lookup(nonce)
    assert store.claim(nonce, "test")["new"] is False
