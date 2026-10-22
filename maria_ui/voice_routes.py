"""Authenticated local audio input; never sends a chat message or takes an action."""
import os
from urllib.parse import urlsplit

from flask import Blueprint, jsonify, request

from agent_core.voice.local_stt import LocalSTT, MAX_AUDIO_BYTES, STTError


def configured_voice_origins(cors_origins, extra_csv=None):
    """Extend only STT's exact allowlist, never Socket.IO or wildcard CORS."""
    extra = os.environ.get("MARIA_STT_ORIGINS", "") if extra_csv is None else extra_csv
    base = list(cors_origins) if isinstance(cors_origins, (list, tuple, set, frozenset)) else []
    accepted = []
    for value in base + str(extra).split(","):
        if not isinstance(value, str):
            continue
        origin = value.strip()
        if not origin or "*" in origin:
            continue
        try:
            parsed = urlsplit(origin)
            if (parsed.scheme not in ("http", "https") or not parsed.hostname
                    or parsed.username is not None or parsed.password is not None
                    or parsed.path or parsed.query or parsed.fragment):
                continue
            # Reject malformed ports rather than leaving unusable auth entries.
            parsed.port
        except ValueError:
            continue
        if origin not in accepted:
            accepted.append(origin)
    return accepted


def create_voice_blueprint(authenticated, bearer_authenticated, allowed_origins, backend=None):
    """Use the existing app's auth callbacks without importing or starting it."""
    voice = Blueprint("local_voice", __name__)
    service = backend if backend is not None else LocalSTT()

    def error(code, message, status):
        response = jsonify(success=False, error=message, code=code)
        response.status_code = status
        response.headers["Cache-Control"] = "no-store"
        return response

    def check_auth():
        if not authenticated():
            return error("unauthorized", "Wymagane jest zalogowanie.", 401)
        return None

    @voice.after_request
    def private_result(response):
        response.headers["Cache-Control"] = "no-store"
        return response

    @voice.get("/api/voice/status")
    def status():
        denied = check_auth()
        if denied is not None:
            return denied
        return jsonify(service.status())

    @voice.post("/api/voice/transcribe")
    def transcribe():
        denied = check_auth()
        if denied is not None:
            return denied
        origins = allowed_origins() if callable(allowed_origins) else allowed_origins
        # Browser cookie requests must name an explicitly allowed origin. Native
        # callers can omit Origin only when the existing Bearer check succeeds.
        origin = request.headers.get("Origin")
        if origin is None:
            if not bearer_authenticated():
                return error("origin_denied", "Nieprawidłowe źródło żądania.", 403)
        elif not isinstance(origins, (list, tuple, set, frozenset)) or origin not in origins or origin == "*":
            return error("origin_denied", "Nieprawidłowe źródło żądania.", 403)
        if request.mimetype != "audio/wav" or request.headers.get("Content-Encoding", "identity").lower() != "identity":
            return error("unsupported_media", "Wymagane jest nagranie audio/wav bez kompresji HTTP.", 415)
        if request.content_length is not None and request.content_length > MAX_AUDIO_BYTES:
            return error("too_large", "Nagranie przekracza limit 1 MiB.", 413)
        try:
            text = service.transcribe_stream(request.stream, request.content_length)
            if not isinstance(text, str):
                return error("invalid_result", "Nieprawidłowy wynik rozpoznawania.", 502)
            return jsonify(success=True, text=text, provider="whisper.cpp", language="pl")
        except STTError as failure:
            return error(failure.code, failure.message, failure.status)
        except Exception:
            # Never return raw native stderr, filesystem paths or exception text.
            return error("transcription_failed", "Nie udało się rozpoznać nagrania.", 502)

    return voice
