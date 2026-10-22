"""Exercise real setup/auth source with temporary files only; no app startup."""
import ast
import importlib.util
import os
from pathlib import Path
import re
import subprocess
from types import SimpleNamespace

from flask import Flask, redirect, request, session, url_for
import pytest

ROOT = Path(__file__).resolve().parents[2]


def _config(tmp_path, monkeypatch, secret):
    import dotenv
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **k: False)
    monkeypatch.setenv("MARIA_PIN", "246810")
    monkeypatch.setenv("MARIA_CORS_ORIGINS", "http://localhost:5000")
    if secret is None:
        monkeypatch.delenv("MARIA_SECRET_KEY", raising=False)
    else:
        monkeypatch.setenv("MARIA_SECRET_KEY", secret)
    # Config's optional Tailscale discovery must never inspect the host here.
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: SimpleNamespace(stdout="", returncode=0))
    directory = tmp_path / "maria_ui"
    directory.mkdir()
    copied = directory / "config.py"
    copied.write_text((ROOT / "maria_ui/config.py").read_text())
    spec = importlib.util.spec_from_file_location("isolated_first_run_config", copied)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _login_client(secret_key):
    """Compile the deployed login handler alone; never import the daemon/app."""
    application = Flask("isolated-login")
    application.config.update(SECRET_KEY=secret_key, TESTING=True)
    application.add_url_rule("/", "index", lambda: "authenticated" if session.get("authenticated") else "denied")
    tree = ast.parse((ROOT / "maria_ui/app.py").read_text())
    login = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "login")
    namespace = {
        "app": application, "request": request, "session": session,
        "redirect": redirect, "url_for": url_for, "UI_PIN": "246810",
        "check_login_allowed": lambda ip: (True, 0),
        "clear_login_failures": lambda ip: None,
        "record_login_failure": lambda ip: None,
        "render_template": lambda *a, **k: "login",
    }
    exec(compile(ast.Module(body=[login], type_ignores=[]), "isolated-login", "exec"), namespace)
    return application.test_client()


@pytest.mark.parametrize("configured", [None, "", "   "])
def test_unset_or_blank_secret_allows_real_pin_login_and_cookie(tmp_path, monkeypatch, configured):
    config = _config(tmp_path, monkeypatch, configured)
    assert config.SECRET_KEY.strip()
    assert len(config.SECRET_KEY) >= 32
    client = _login_client(config.SECRET_KEY)
    response = client.post("/login", data={"pin": "246810"})
    assert response.status_code == 302
    assert "HttpOnly" in response.headers["Set-Cookie"]
    assert client.get("/").data == b"authenticated"


def test_existing_nonempty_secret_is_preserved_exactly(tmp_path, monkeypatch):
    configured = " operator-kept-nonempty-session-secret "
    config = _config(tmp_path, monkeypatch, configured)
    assert config.SECRET_KEY == configured


def _credentials_block():
    script = (ROOT / "install.sh").read_text()
    return script.split("# BEGIN INITIAL CREDENTIALS\n", 1)[1].split("# END INITIAL CREDENTIALS", 1)[0]


def _run_setup(tmp_path):
    # Only the actual credential block runs, not installers/downloads/services.
    env = dict(os.environ)
    env.pop("BASH_ENV", None)
    return subprocess.run(["bash", "-c", "set -e\numask 000\n" + _credentials_block()],
                          cwd=tmp_path, env=env, check=True, capture_output=True, text=True, timeout=10)


def _template(tmp_path):
    (tmp_path / ".env.example").write_text("MARIA_PIN=change-me-123\nMARIA_SECRET_KEY=\nMARIA_HOST=127.0.0.1\n")


def test_installer_generates_private_persistent_credentials_and_preserves_rerun(tmp_path):
    _template(tmp_path)
    response = _run_setup(tmp_path)
    path = tmp_path / ".env"
    data = path.read_text()
    pin = re.search(r"^MARIA_PIN=(.+)$", data, re.MULTILINE).group(1)
    key = re.search(r"^MARIA_SECRET_KEY=(.+)$", data, re.MULTILINE).group(1)
    assert re.fullmatch(r"[0-9a-f]{8}", pin)
    assert re.fullmatch(r"[0-9a-f]{64}", key)
    assert key not in response.stdout + response.stderr
    assert pin in response.stdout
    assert path.stat().st_mode & 0o777 == 0o600
    before = (path.stat().st_ino, path.stat().st_mtime_ns, data)
    _run_setup(tmp_path)
    assert (path.stat().st_ino, path.stat().st_mtime_ns, path.read_text()) == before


def test_installer_keeps_existing_operator_config_even_when_secret_blank(tmp_path):
    _template(tmp_path)
    path = tmp_path / ".env"
    data = "MARIA_PIN=operator-pin\nMARIA_SECRET_KEY=\nCUSTOM=value\n"
    path.write_text(data)
    path.chmod(0o640)
    _run_setup(tmp_path)
    assert path.read_text() == data
    assert path.stat().st_mode & 0o777 == 0o640


def test_installer_preserves_existing_and_dangling_symlinks(tmp_path):
    _template(tmp_path)
    path = tmp_path / ".env"
    target = tmp_path / "operator-config"
    target.write_text("MARIA_SECRET_KEY=operator-secret\n")
    path.symlink_to(target.name)
    _run_setup(tmp_path)
    assert path.is_symlink()
    assert target.read_text() == "MARIA_SECRET_KEY=operator-secret\n"
    target.unlink()
    _run_setup(tmp_path)
    assert path.is_symlink()
    assert not target.exists()


def test_secret_file_is_private_from_birth(tmp_path, monkeypatch):
    import secrets
    _template(tmp_path)
    # Execute the exact Python payload under an intentionally permissive umask.
    block = _credentials_block()
    payload = block.split("<<'MARIA_CREDENTIALS'\n", 1)[1].split("\nMARIA_CREDENTIALS", 1)[0]
    native_open = os.open
    created = []
    def guarded_open(path, flags, mode=0o777, **kwargs):
        if str(path) == ".env":
            assert mode == 0o600
            assert flags & os.O_EXCL
            created.append(path)
        return native_open(path, flags, mode, **kwargs)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(os, "open", guarded_open)
    # Suppress display of generated test-only PIN, not the checks above.
    exec(compile(payload, "isolated-credential-creation", "exec"), {"print": lambda *a: None})
    assert created == [".env"]
