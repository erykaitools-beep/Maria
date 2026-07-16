"""Native-app token auth tests (2026-06-17).

The native APK talks to Maria over a different origin (Tailscale/LAN) where the
session cookie does not apply, so it authenticates with a Bearer API token
issued by POST /api/auth/login after a correct PIN. These tests pin the token
and PIN and exercise the new surface: token issuance, Bearer acceptance, and --
the part that matters -- that NO bad/blank token or wrong PIN slips through.
"""

import pytest

import maria_ui.app as ui_app

_TOKEN = "TESTTOKEN_abc123"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(ui_app, "UI_PIN", "123456")
    monkeypatch.setattr(ui_app, "get_api_token", lambda: _TOKEN)
    ui_app.app.config["TESTING"] = True
    with ui_app._login_lock:
        ui_app._login_failures.clear()
    yield ui_app.app.test_client()
    with ui_app._login_lock:
        ui_app._login_failures.clear()


class TestTokenLogin:
    def test_bad_pin_rejected(self, client):
        resp = client.post("/api/auth/login", json={"pin": "000000"})
        assert resp.status_code == 401
        assert resp.get_json()["ok"] is False
        with ui_app._login_lock:
            assert len(ui_app._login_failures.get("127.0.0.1", [])) == 1

    def test_good_pin_returns_token(self, client):
        resp = client.post("/api/auth/login", json={"pin": "123456"})
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        assert body["token"] == _TOKEN

    def test_login_throttled_after_max_failures(self, client):
        for _ in range(ui_app.LOGIN_MAX_FAILURES):
            client.post("/api/auth/login", json={"pin": "000000"})
        resp = client.post("/api/auth/login", json={"pin": "000000"})
        assert resp.status_code == 429
        # Lockout also blocks a CORRECT pin (penalty, not a sieve).
        resp = client.post("/api/auth/login", json={"pin": "123456"})
        assert resp.status_code == 429


class TestBearerAuth:
    def test_ping_without_auth_redirects(self, client):
        resp = client.get("/api/auth/ping")
        assert resp.status_code == 302

    def test_ping_with_valid_bearer(self, client):
        resp = client.get(
            "/api/auth/ping", headers={"Authorization": f"Bearer {_TOKEN}"}
        )
        assert resp.status_code == 200
        assert resp.get_json()["ok"] is True

    def test_wrong_bearer_rejected(self, client):
        resp = client.get(
            "/api/auth/ping", headers={"Authorization": "Bearer WRONG"}
        )
        assert resp.status_code == 302

    def test_blank_bearer_rejected(self, client):
        # An empty token must never authenticate, even if get_api_token were ''.
        resp = client.get("/api/auth/ping", headers={"Authorization": "Bearer "})
        assert resp.status_code == 302

    def test_non_bearer_scheme_rejected(self, client):
        resp = client.get(
            "/api/auth/ping", headers={"Authorization": f"Basic {_TOKEN}"}
        )
        assert resp.status_code == 302

    def test_bearer_reaches_protected_api(self, client):
        # is_authenticated() via token unlocks the real protected surface.
        resp = client.get(
            "/api/status/full", headers={"Authorization": f"Bearer {_TOKEN}"}
        )
        assert resp.status_code != 302


class TestTokenHelper:
    def test_blank_bearer_helper_false_even_if_token_blank(self, client, monkeypatch):
        # Defense in depth: if the server token resolved to '' (misconfig),
        # a blank/missing Authorization header must still not authenticate.
        monkeypatch.setattr(ui_app, "get_api_token", lambda: "")
        resp = client.get("/api/auth/ping", headers={"Authorization": "Bearer "})
        assert resp.status_code == 302
