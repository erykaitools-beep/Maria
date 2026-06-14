"""Login brute-force throttle tests (audyt 2026-06-12).

The 6-digit PIN on a 0.0.0.0:5000 UI had no attempt limit (1e6 keyspace,
fail2ban guards ssh only, no reverse proxy). Throttle lives in the /login
handler itself: LOGIN_MAX_FAILURES failed attempts per LOGIN_WINDOW_SEC
per IP -> 429 until the window slides.
"""

import time

import pytest

import maria_ui.app as ui_app


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(ui_app, "UI_PIN", "123456")
    ui_app.app.config["TESTING"] = True
    with ui_app._login_lock:
        ui_app._login_failures.clear()
    yield ui_app.app.test_client()
    with ui_app._login_lock:
        ui_app._login_failures.clear()


def _post_pin(client, pin):
    return client.post("/login", data={"pin": pin})


class TestLoginThrottle:
    def test_wrong_pin_rejected_and_recorded(self, client):
        resp = _post_pin(client, "000000")
        assert resp.status_code == 200
        assert b"Nieprawidlowy PIN" in resp.data
        with ui_app._login_lock:
            assert len(ui_app._login_failures.get("127.0.0.1", [])) == 1

    def test_lockout_after_max_failures(self, client):
        for _ in range(ui_app.LOGIN_MAX_FAILURES):
            resp = _post_pin(client, "000000")
            assert resp.status_code == 200

        resp = _post_pin(client, "000000")
        assert resp.status_code == 429
        assert b"Za duzo prob" in resp.data
        # Lockout blokuje tez probe z POPRAWNYM pinem (kara, nie sito).
        resp = _post_pin(client, "123456")
        assert resp.status_code == 429

    def test_lockout_expires_after_window(self, client):
        for _ in range(ui_app.LOGIN_MAX_FAILURES):
            _post_pin(client, "000000")
        # Przesun wszystkie porazki poza okno.
        stale = time.time() - ui_app.LOGIN_WINDOW_SEC - 1
        with ui_app._login_lock:
            ui_app._login_failures["127.0.0.1"] = [
                stale for _ in range(ui_app.LOGIN_MAX_FAILURES)
            ]
        resp = _post_pin(client, "000000")
        assert resp.status_code == 200  # znow wolno probowac

    def test_correct_pin_clears_failures(self, client):
        _post_pin(client, "000000")
        resp = _post_pin(client, "123456")
        assert resp.status_code == 302  # redirect na index
        with ui_app._login_lock:
            assert "127.0.0.1" not in ui_app._login_failures

    def test_prune_bounds_memory(self, client):
        """Wpisy starych IP znikaja przy kolejnym sprawdzeniu (bounded dict)."""
        stale = time.time() - ui_app.LOGIN_WINDOW_SEC - 1
        with ui_app._login_lock:
            ui_app._login_failures["10.0.0.99"] = [stale, stale]
        allowed, _ = ui_app.check_login_allowed("127.0.0.1")
        assert allowed
        with ui_app._login_lock:
            assert "10.0.0.99" not in ui_app._login_failures
