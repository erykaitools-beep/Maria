"""Isolated Flask routes; no live process, auth file, host, or model access."""
from unittest.mock import create_autospec
from uuid import uuid4

from flask import Flask, request, session
import pytest

from agent_core.llm.kritaqo_work_service import WorkService, get_work_service
from maria_ui.chat_turns import ChatTurnStore
from maria_ui.work_routes import create_work_blueprint

ORIGIN = "https://maria.test:8443"


@pytest.fixture
def setup(tmp_path):
    app = Flask(__name__)
    app.config.update(TESTING=True, SECRET_KEY="isolated-only")
    service, factory = create_autospec(WorkService, instance=True), create_autospec(get_work_service)
    factory.return_value = service
    service.projects.return_value = {"projects": [], "selectedProjectKey": None}
    service.tasks.return_value = {"tasks": []}
    service.select_project.return_value = {"projects": [], "selectedProjectKey": "fixture"}
    service.artifact.return_value = {"ok": False, "errorCode": "artifact_unsupported"}
    store = ChatTurnStore(tmp_path / "turns")
    bearer = lambda: request.headers.get("Authorization") == "Bearer test-only"
    app.register_blueprint(create_work_blueprint(lambda: session.get("authenticated") or bearer(), bearer, [ORIGIN], factory, lambda: store))
    return app.test_client(), service, factory, store


def login(client):
    with client.session_transaction() as current:
        current["authenticated"] = True


def test_unauthenticated_routes_never_redirect_or_touch_service(setup):
    client, service, factory, store = setup
    for url in ["/api/work/projects", "/api/work/tasks", "/api/work/tasks/a/artifact?path=a.md", "/api/chat/turn/" + uuid4().hex]:
        response = client.get(url)
        assert response.status_code == 401
        assert "Location" not in response.headers
        assert response.headers["Cache-Control"] == "no-store"
    assert client.post("/api/work/selection", json={"key": "fixture"}).status_code == 401
    factory.assert_not_called()


def test_selection_requires_exact_origin_or_bearer_and_small_schema(setup):
    client, service, factory, store = setup
    login(client)
    for origin in [None, "null", ORIGIN + ".evil", "*"]:
        response = client.post("/api/work/selection", json={"key": "fixture"}, headers={} if origin is None else {"Origin": origin})
        assert response.status_code == 403
    factory.assert_not_called()
    response = client.post("/api/work/selection", json={"key": "fixture"}, headers={"Origin": ORIGIN})
    assert response.status_code == 200
    service.select_project.assert_called_once_with("fixture")
    assert client.post("/api/work/selection", json={"key": "fixture"}, headers={"Authorization": "Bearer test-only"}).status_code == 200
    for body in [{"key": "fixture", "submit": True}, {"key": []}, {}]:
        assert client.post("/api/work/selection", json=body, headers={"Origin": ORIGIN}).status_code == 400
    assert client.post("/api/work/selection", data="x" * 2049, content_type="application/json", headers={"Origin": ORIGIN}).status_code == 413


def test_tasks_artifact_unavailable_and_safe_errors_keep_login(setup):
    client, service, factory, store = setup
    login(client)
    assert client.get("/api/work/tasks").json == {"tasks": []}
    result = client.get("/api/work/tasks/a/artifact?path=report.md")
    assert result.status_code == 200 and result.json["errorCode"] == "artifact_unsupported"
    service.artifact.assert_called_once_with("a", "report.md")
    service.projects.side_effect = RuntimeError("credential and private path")
    response = client.get("/api/work/projects")
    assert response.status_code == 503
    assert "credential" not in response.text
    assert client.get("/api/work/tasks").status_code == 200
    service.submit.assert_not_called()


def test_chat_turn_recovery_has_no_execution_and_preserves_unknown(setup):
    client, service, factory, store = setup
    login(client)
    nonce = uuid4().hex
    assert client.get("/api/chat/turn/" + nonce).status_code == 404
    store.claim(nonce, "test")
    assert client.get("/api/chat/turn/" + nonce).json["state"] == "pending"
    store.complete(nonce, {"success": True, "message": "wynik"})
    value = client.get("/api/chat/turn/" + nonce).json
    assert value["response"]["message"] == "wynik"
    assert "interaction_id" not in value
    factory.assert_not_called()
