"""Launcher tests use only stdlib, temporary clones and fake IO boundaries."""
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import types
import unittest
from unittest.mock import patch


SOURCE = Path(__file__).resolve().parents[2] / "scripts" / "start_chat.py"
spec = importlib.util.spec_from_file_location("isolated_start_chat", SOURCE)
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


def dotenv_values(path, interpolate=False):
    assert interpolate is False
    if not Path(path).exists():
        return {}
    return dict(line.split("=", 1) for line in Path(path).read_text().splitlines()
                if line and not line.startswith("#"))


class FakeSocket:
    failure = None
    bound = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def bind(self, address):
        self.bound.append(address)
        if self.failure:
            raise self.failure


class StartChatTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.addCleanup(os.chdir, Path.cwd())
        self.addCleanup(sys.path.__setitem__, slice(None), list(sys.path))
        self.enter = contextlib.ExitStack()
        self.addCleanup(self.enter.close)
        self.enter.enter_context(patch.object(launcher, "ROOT", self.root))
        self.enter.enter_context(patch.dict(os.environ, {}, clear=True))
        self.enter.enter_context(contextlib.redirect_stdout(io.StringIO()))
        self.enter.enter_context(contextlib.redirect_stderr(io.StringIO()))

    def config(self, extra=""):
        path = self.root / ".env"
        path.write_text("MARIA_PIN=fixture-pin\nMARIA_SECRET_KEY=fixture-secret\n" + extra)
        return path

    def prepared(self, argv, *, models=None):
        runs = []
        FakeSocket.bound = []
        FakeSocket.failure = None
        self.enter.enter_context(patch.object(launcher, "available_models", lambda url: models or {"fixture:latest"}))
        self.enter.enter_context(patch.object(launcher.socket, "socket", FakeSocket))
        self.enter.enter_context(patch.dict(sys.modules, {
            "dotenv": types.SimpleNamespace(dotenv_values=dotenv_values),
            "maria_ui.app": types.SimpleNamespace(app=object(), socketio=types.SimpleNamespace(
                run=lambda app, **kwargs: runs.append(kwargs))),
        }))
        return lambda: launcher.main(["--prepared", "--model", "fixture", *argv]), runs

    def test_new_configuration_private_and_exclusive(self):
        path = self.root / ".env"
        launcher.new_config(path, "fixture:latest")
        before = path.read_bytes()
        values = dotenv_values(path)
        self.assertEqual(values["MARIA_CHAT_MODEL"], "fixture:latest")
        self.assertTrue(values["MARIA_PIN"] and values["MARIA_SECRET_KEY"])
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        with self.assertRaises(FileExistsError):
            launcher.new_config(path, "other")
        self.assertEqual(path.read_bytes(), before)

    def test_dangling_config_symlink_never_followed(self):
        path = self.root / ".env"
        target = self.root / "not-created"
        path.symlink_to(target)
        with self.assertRaises(FileExistsError):
            launcher.new_config(path, "fixture")
        self.assertFalse(target.exists())

    def test_model_name_cannot_inject_configuration(self):
        for model in ("fixture\nMARIA_HOST=remote", "a b", "a=b", "a#b", "", "a'b"):
            with self.subTest(model=model), self.assertRaises(ValueError):
                launcher.new_config(self.root / ".env", model)
            self.assertFalse((self.root / ".env").exists())

    def test_local_urls_only(self):
        for value in ("http://127.0.0.1:11434/", "http://localhost:11434", "http://[::1]:11434"):
            self.assertEqual(launcher.local_url(value), value.rstrip("/"))
        for value in ("https://localhost", "http://example.org", "http://localhost.evil", "http://user@localhost",
                      "http://localhost/x", "http://localhost?q=x", "http://localhost/#x", "http://localhost:99999"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                launcher.local_url(value)

    def test_metadata_request_is_bounded_proxy_free_and_no_redirect(self):
        seen = []
        class Reply(io.BytesIO):
            pass
        class Opener:
            def open(self, url, timeout):
                seen.append((url, timeout))
                return Reply(json.dumps({"models": [{"name": "fixture:latest"}, {}, "bad"]}).encode())
        def build(*handlers):
            self.assertEqual(handlers[0].proxies, {})
            self.assertIsInstance(handlers[1], launcher.NoRedirect)
            self.assertIsNone(handlers[1].redirect_request(None, None, 302, "", {}, "http://remote"))
            return Opener()
        with patch.object(launcher, "build_opener", build):
            self.assertEqual(launcher.available_models("http://127.0.0.1:11434"), {"fixture:latest"})
        self.assertEqual(seen, [("http://127.0.0.1:11434/api/tags", 5)])

    def test_oversized_model_metadata_rejected(self):
        opener = types.SimpleNamespace(open=lambda *args, **kwargs: io.BytesIO(b"x" * (1024 * 1024 + 1)))
        with patch.object(launcher, "build_opener", lambda *args: opener), self.assertRaisesRegex(ValueError, "large"):
            launcher.available_models("http://localhost")

    def test_missing_model_never_downloads(self):
        self.assertEqual(launcher.choose_model("fixture", {"fixture:latest"}), "fixture:latest")
        self.assertEqual(launcher.choose_model("fixture:v2", {"fixture:v2"}), "fixture:v2")
        with self.assertRaisesRegex(ValueError, "not installed"):
            launcher.choose_model("missing", {"fixture:latest"})

    def test_prepared_existing_environment_preserved_but_local_profile_forced(self):
        path = self.config("MARIA_CHAT_BACKEND=codex\nMARIA_HOST=0.0.0.0\nMARIA_BACKGROUND_REASONING=1\n")
        before = path.read_bytes()
        os.environ.update(MARIA_CHAT_BACKEND="codex", OLLAMA_HOST="http://remote", MARIA_CHAT_ONLY="0")
        invoke, runs = self.prepared(["--port", "5050"])
        self.assertEqual(invoke(), 0)
        self.assertEqual(path.read_bytes(), before)
        for key, value in {"MARIA_CHAT_ONLY": "1", "MARIA_CHAT_BACKEND": "ollama",
                           "MARIA_CHAT_MODEL": "fixture:latest", "OLLAMA_HOST": "http://127.0.0.1:11434",
                           "MARIA_HOST": "127.0.0.1", "MARIA_BACKGROUND_REASONING": "0",
                           "MARIA_TELEGRAM_INTEGRATION": "0", "MARIA_CONDUCTOR_INTEGRATION": "0"}.items():
            self.assertEqual(os.environ[key], value)
        self.assertEqual(FakeSocket.bound, [("127.0.0.1", 5050)])
        self.assertEqual(runs, [{"host": "127.0.0.1", "port": 5050, "debug": False,
                                 "use_reloader": False, "allow_unsafe_werkzeug": True}])

    def test_existing_invalid_environment_preserved_with_actionable_failure(self):
        path = self.root / ".env"
        path.write_text("MARIA_PIN=\nMARIA_CHAT_BACKEND=codex\n")
        before = path.read_bytes()
        invoke, runs = self.prepared([])
        with self.assertRaisesRegex(ValueError, "preserved.*MARIA_PIN.*MARIA_SECRET_KEY"):
            invoke()
        self.assertEqual(path.read_bytes(), before)
        self.assertFalse(runs)

    def test_prepare_only_creates_config_without_socket_or_app_start(self):
        invoke, runs = self.prepared(["--prepare-only"])
        self.assertEqual(invoke(), 0)
        self.assertTrue((self.root / ".env").is_file())
        self.assertFalse(FakeSocket.bound or runs)

    def test_occupied_port_does_not_start_or_alter_config(self):
        path = self.config()
        before = path.read_bytes()
        invoke, runs = self.prepared([])
        FakeSocket.failure = OSError("occupied")
        with self.assertRaisesRegex(ValueError, "unavailable.*not stopped"):
            invoke()
        self.assertFalse(runs)
        self.assertEqual(path.read_bytes(), before)

    def test_invalid_port_fails_before_metadata_or_bootstrap(self):
        with patch.object(launcher, "available_models", side_effect=AssertionError("network")):
            for port in ("0", "65536"):
                with self.subTest(port=port), self.assertRaises(SystemExit) as raised:
                    launcher.main(["--port", port])
                self.assertEqual(raised.exception.code, 2)

    def test_bootstrap_reexecutes_prepared_once_with_exact_arguments(self):
        executable = self.root / "fake-python"
        commands = []
        class Reexecuted(BaseException):
            pass
        def execv(executable, command):
            commands.append((command, {"cwd": Path.cwd()}))
            raise Reexecuted()
        with patch.object(launcher, "available_models", lambda _: {"fixture:latest"}), \
                patch.object(launcher, "ensure_environment", lambda root: executable), \
                patch.object(launcher.os, "execv", execv), \
                patch.object(launcher.subprocess, "call", lambda command, **kwargs: commands.append((command, kwargs)) or 7):
            if os.name == "posix":
                with self.assertRaises(Reexecuted):
                    launcher.main(["--model", "fixture", "--prepare-only"])
            else:
                self.assertEqual(launcher.main(["--model", "fixture", "--prepare-only"]), 7)
        self.assertEqual(commands[0][0], [str(executable), str(SOURCE), "--model", "fixture", "--prepare-only", "--prepared"])
        self.assertEqual(commands[0][1], {"cwd": self.root})
        self.assertFalse((self.root / ".env").exists())

    def test_dependency_marker_installs_only_after_requirements_change(self):
        requirements = self.root / "requirements-core.txt"
        requirements.write_text("fixture-dependency\n")
        calls = []
        def create(builder, directory):
            executable = directory / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
            executable.parent.mkdir(parents=True)
            executable.touch()
        with patch.object(launcher.venv.EnvBuilder, "create", create), \
                patch.object(launcher.subprocess, "run", lambda command, **kwargs: calls.append((command, kwargs))):
            executable = launcher.ensure_environment(self.root)
            self.assertEqual(launcher.ensure_environment(self.root), executable)
            self.assertEqual(len(calls), 1)
            requirements.write_text("changed-fixture\n")
            launcher.ensure_environment(self.root)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0], ([str(executable), "-m", "pip", "install", "-r", str(requirements)], {"check": True}))
        marker = self.root / ".venv-chat" / ".maria-core-requirements"
        self.assertEqual(marker.read_text().strip(), hashlib.sha256(requirements.read_bytes()).hexdigest())

    def test_failed_dependency_install_does_not_mark_environment_ready(self):
        (self.root / "requirements-core.txt").write_text("fixture\n")
        executable = self.root / ".venv-chat" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        executable.parent.mkdir(parents=True)
        executable.touch()
        with patch.object(launcher.subprocess, "run", side_effect=launcher.subprocess.CalledProcessError(1, "fake-pip")), \
                self.assertRaises(launcher.subprocess.CalledProcessError):
            launcher.ensure_environment(self.root)
        self.assertFalse((self.root / ".venv-chat" / ".maria-core-requirements").exists())


if __name__ == "__main__":
    unittest.main()
