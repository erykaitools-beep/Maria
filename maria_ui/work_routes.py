"""Authenticated project/task reads and explicit project selection.

These routes never submit model work. Errors are JSON, not login redirects.
"""
import json

from flask import Blueprint, jsonify, request

from maria_ui.chat_turns import valid_request_id


def create_work_blueprint(authenticated, bearer_authenticated, allowed_origins, service_factory, turn_store_factory):
    work = Blueprint("project_work", __name__)

    def error(code, status, message="Operacja jest teraz niedostępna."):
        return jsonify(ok=False, errorCode=code, error=message), status

    @work.before_request
    def authenticate():
        if not authenticated():
            return error("unauthorized", 401, "Wymagane jest zalogowanie.")

    @work.after_request
    def private_result(response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    def call(method, *args):
        try:
            result = getattr(service_factory(), method)(*args)
            return jsonify(result)
        except (ValueError, KeyError):
            return error("invalid_selection", 409)
        except Exception:
            return error("service_unavailable", 503)

    @work.get("/api/work/projects")
    def projects():
        return call("projects")

    @work.get("/api/work/tasks")
    def tasks():
        return call("tasks")

    @work.post("/api/work/selection")
    def selection():
        origin = request.headers.get("Origin")
        origins = allowed_origins() if callable(allowed_origins) else allowed_origins
        if origin is None:
            if not bearer_authenticated():
                return error("origin_denied", 403)
        elif not isinstance(origins, (list, tuple, set, frozenset)) or origin == "*" or origin not in origins:
            return error("origin_denied", 403)
        if request.mimetype != "application/json" or request.headers.get("Content-Encoding", "identity").lower() != "identity":
            return error("unsupported_media", 415)
        if request.content_length is not None and request.content_length > 2048:
            return error("too_large", 413)
        raw = request.stream.read(2049)
        if len(raw) > 2048:
            return error("too_large", 413)
        try:
            body = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            return error("invalid_request", 400)
        if not isinstance(body, dict) or set(body) != {"key"} or not isinstance(body["key"], str) or not 1 <= len(body["key"]) <= 200:
            return error("invalid_request", 400)
        return call("select_project", body["key"])

    @work.get("/api/work/tasks/<task_key>/artifact")
    def artifact(task_key):
        path = request.args.get("path", "")
        if not 1 <= len(task_key) <= 200 or not 1 <= len(path) <= 1024:
            return error("invalid_request", 400)
        return call("artifact", task_key, path)

    @work.get("/api/chat/turn/<request_id>")
    def chat_turn(request_id):
        if not valid_request_id(request_id):
            return error("invalid_request", 400)
        try:
            value = turn_store_factory().lookup(request_id)
        except Exception:
            return error("receipt_unavailable", 503)
        if value is None:
            return error("not_seen", 404, "Brak potwierdzenia przyjęcia tej wiadomości. Nie wysłano jej ponownie.")
        return jsonify(value)

    return work
