"""Exercise the blueprint in an isolated Flask app; no live Maria imports."""
import ast
import hmac
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from agent_core.tests.spec_helpers import specced
import wave

from flask import Flask, request, session
from werkzeug.test import EnvironBuilder

from agent_core.voice.local_stt import LocalSTT, MAX_AUDIO_BYTES, STTError
from maria_ui.voice_routes import configured_voice_origins, create_voice_blueprint

ORIGIN = "https://192.0.2.10:8443"


def audio():
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(b"\0\0" * 160)
    return buffer.getvalue()


class VoiceRouteTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(TESTING=True, SECRET_KEY="offline-test-only")
        self.backend = specced(LocalSTT)
        self.backend.status.return_value = {"available": True, "provider": "whisper.cpp", "language": "pl", "max_seconds": 30, "sample_rate": 16000}
        self.backend.transcribe_stream.return_value = "Próba transkrypcji."
        self.app.register_blueprint(create_voice_blueprint(
            lambda: bool(session.get("authenticated")) or request.headers.get("Authorization") == "Bearer test-only",
            lambda: request.headers.get("Authorization") == "Bearer test-only",
            [ORIGIN], self.backend))
        self.client = self.app.test_client()

    def login(self):
        with self.client.session_transaction() as current:
            current["authenticated"] = True

    def post(self, origin=ORIGIN, **options):
        headers = options.pop("headers", {})
        if origin is not None:
            headers["Origin"] = origin
        return self.client.post("/api/voice/transcribe", data=options.pop("data", audio()), content_type=options.pop("content_type", "audio/wav"), headers=headers, **options)

    def test_auth_json_no_redirect_no_processing(self):
        for response in [self.client.get("/api/voice/status"), self.post()]:
            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.json["code"], "unauthorized")
            self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.backend.status.assert_not_called()
        self.backend.transcribe_stream.assert_not_called()

    def test_status_is_small_and_does_not_transcribe(self):
        self.login()
        response = self.client.get("/api/voice/status")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, self.backend.status.return_value)
        self.backend.transcribe_stream.assert_not_called()

    def test_cookie_origin_and_bearer_without_origin(self):
        self.login()
        for origin in [None, "null", "https://untrusted.invalid", ORIGIN + ".evil", ORIGIN + "," + ORIGIN]:
            self.assertEqual(self.post(origin).status_code, 403)
        self.backend.transcribe_stream.assert_not_called()
        response = self.post()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {"success": True, "text": "Próba transkrypcji.", "provider": "whisper.cpp", "language": "pl"})
        self.assertEqual(self.post(None, headers={"Authorization": "Bearer test-only"}).status_code, 200)
        self.assertEqual(self.post("https://untrusted.invalid", headers={"Authorization": "Bearer test-only"}).status_code, 403)

    def test_format_encoding_and_declared_limit_before_backend(self):
        self.login()
        self.assertEqual(self.post(content_type="audio/webm").status_code, 415)
        self.assertEqual(self.post(headers={"Content-Encoding": "gzip"}).status_code, 415)
        self.assertEqual(self.post(data=b"x" * (MAX_AUDIO_BYTES + 1)).status_code, 413)
        self.backend.transcribe_stream.assert_not_called()

    def test_safe_failures_and_no_unexpected_error_disclosure(self):
        self.login()
        for failure in [STTError("busy", "Trwa poprzednie nagranie.", 409), STTError("timeout", "Przekroczono czas.", 504), RuntimeError("/private/path credential=not-public")]:
            self.backend.transcribe_stream.side_effect = failure
            response = self.post()
            self.assertFalse(response.json["success"])
            self.assertNotIn("private", response.get_data(as_text=True))
            self.assertNotIn("credential", response.get_data(as_text=True))
            self.assertEqual(response.status_code, failure.status if isinstance(failure, STTError) else 502)

    def test_missing_content_length_is_read_with_strict_bound(self):
        self.login()
        captured = []
        def transcribe(stream, length):
            self.assertIsNone(length)
            captured.append(stream.read(MAX_AUDIO_BYTES + 1))
            return ""
        self.backend.transcribe_stream.side_effect = transcribe
        env = EnvironBuilder(path="/api/voice/transcribe", method="POST", data=audio(), content_type="audio/wav", headers={"Origin": ORIGIN}).get_environ()
        env.pop("CONTENT_LENGTH", None)
        env["wsgi.input_terminated"] = True
        env["HTTP_AUTHORIZATION"] = "Bearer test-only"
        # test_client.open rebuilds a missing length as zero; exercise the
        # original chunked WSGI environment without that normalization.
        with self.app.request_context(env):
            response = self.app.full_dispatch_request()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(captured, [audio()])

    def test_real_adapter_rejects_malformed_before_process(self):
        with tempfile.TemporaryDirectory() as folder:
            binary, model = Path(folder) / "cli", Path(folder) / "model"
            binary.write_bytes(b"stub")
            binary.chmod(0o700)
            model.write_bytes(b"stub")
            popen = Mock(side_effect=AssertionError("must not spawn"))
            adapter = LocalSTT(str(binary), str(model), popen=popen)
            app = Flask("invalid-wav")
            app.register_blueprint(create_voice_blueprint(lambda: True, lambda: False, [ORIGIN], adapter))
            response = app.test_client().post("/api/voice/transcribe", data=b"invalid", content_type="audio/wav", headers={"Origin": ORIGIN})
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json["code"], "invalid_audio")
            popen.assert_not_called()


class ExistingAuthIntegrationTests(unittest.TestCase):
    """Use app.py's actual auth bodies without its runtime initialization."""
    def test_exact_configured_origins_never_expand_socketio(self):
        legacy = ["http://192.0.2.10:5000", "*"]
        original = list(legacy)
        with patch.dict(os.environ, {"MARIA_STT_ORIGINS": ORIGIN + ", *,https://*.invalid, null,https://bad.invalid/path," + ORIGIN}):
            result = configured_voice_origins(legacy)
        self.assertEqual(result, [legacy[0], ORIGIN])
        self.assertEqual(legacy, original)
        self.assertEqual(configured_voice_origins("*", "*"), [])

    def test_existing_cookie_bearer_auth_with_caddy_lan_origin_passthrough(self):
        app_path = Path(__file__).resolve().parents[2] / "maria_ui" / "app.py"
        tree = ast.parse(app_path.read_text())
        names = {"_bearer_token_valid", "is_authenticated"}
        definitions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
        self.assertEqual({node.name for node in definitions}, names)
        namespace = {"request": request, "session": session, "hmac": hmac,
                     "get_api_token": lambda: "offline-known-token"}
        exec(compile(ast.Module(body=definitions, type_ignores=[]), "existing_app_auth", "exec"), namespace)
        backend = specced(LocalSTT)
        backend.status.return_value = {"available": True, "provider": "whisper.cpp", "language": "pl", "max_seconds": 30, "sample_rate": 16000}
        received = []
        def transcribe(stream, length):
            received.append((request.headers.get("Origin"), request.remote_addr, stream.read(MAX_AUDIO_BYTES + 1), length))
            return "Tekst bez automatycznego wysyłania."
        backend.transcribe_stream.side_effect = transcribe
        app = Flask("existing-auth-integration")
        app.config.update(TESTING=True, SECRET_KEY="offline-session-only")
        cors = ["http://192.0.2.10:5000"]
        with patch.dict(os.environ, {"MARIA_STT_ORIGINS": ORIGIN}):
            app.register_blueprint(create_voice_blueprint(
                namespace["is_authenticated"], namespace["_bearer_token_valid"],
                lambda: configured_voice_origins(cors), backend))
            client = app.test_client()
            self.assertEqual(client.get("/api/voice/status").status_code, 401)
            self.assertEqual(client.get("/api/voice/status", headers={"Authorization": "Bearer invalid"}).status_code, 401)
            with client.session_transaction(base_url=ORIGIN) as current:
                current["authenticated"] = True
            self.assertEqual(client.get("/api/voice/status", base_url=ORIGIN).status_code, 200)
            self.assertEqual(client.post("/api/voice/transcribe", base_url=ORIGIN, data=audio(), content_type="audio/wav").status_code, 403)
            response = client.post("/api/voice/transcribe", data=audio(), content_type="audio/wav",
                                   base_url=ORIGIN,
                                   headers={"Origin": ORIGIN, "Host": "192.0.2.10:8443", "X-Forwarded-Proto": "https"},
                                   environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(received[-1], (ORIGIN, "127.0.0.1", audio(), len(audio())))
            self.assertEqual(response.json["text"], "Tekst bez automatycznego wysyłania.")
            native = app.test_client()
            self.assertEqual(native.post("/api/voice/transcribe", data=audio(), content_type="audio/wav", headers={"Authorization": "Bearer offline-known-token"}).status_code, 200)
            self.assertEqual(cors, ["http://192.0.2.10:5000"])


if __name__ == "__main__":
    unittest.main()
