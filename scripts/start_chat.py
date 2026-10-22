#!/usr/bin/env python3
"""Prepare a small local chat installation, then run its browser interface.

Uses an already installed Ollama model. Does not install/start Ollama, download
models, start the daemon, or change an existing .env. See QUICKSTART.md.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, build_opener
import venv


ROOT = Path(__file__).resolve().parents[1]


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def local_url(value):
    parts = urlsplit(value)
    if (parts.scheme != "http" or parts.hostname not in {"localhost", "127.0.0.1", "::1"}
            or parts.username or parts.password or parts.path not in {"", "/"}
            or parts.query or parts.fragment):
        raise ValueError("Use a local Ollama URL, such as http://127.0.0.1:11434")
    # Accessing .port also rejects malformed/out-of-range ports.
    _ = parts.port
    return value.rstrip("/")


def available_models(url):
    # Bypass HTTP_PROXY for this explicitly local request.
    with build_opener(ProxyHandler({}), NoRedirect()).open(url + "/api/tags", timeout=5) as reply:
        data = reply.read(1024 * 1024 + 1)
    if len(data) > 1024 * 1024:
        raise ValueError("Ollama returned an unexpectedly large model list")
    return {item["name"] for item in json.loads(data)["models"]
            if isinstance(item, dict) and isinstance(item.get("name"), str)}


def choose_model(requested, installed):
    if requested in installed:
        return requested
    if ":" not in requested and requested + ":latest" in installed:
        return requested + ":latest"
    choices = ", ".join(json.dumps(name) for name in sorted(installed)) or "none"
    raise ValueError(
        f"Model {requested!r} is not installed. Available models: {choices}. "
        "Use --model NAME, or download a chat model yourself with ollama pull NAME."
    )


def ensure_environment(root):
    directory = root / ".venv-chat"
    executable = directory / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not executable.is_file():
        print("Creating .venv-chat (Python's venv/ensurepip support is required)...", flush=True)
        venv.EnvBuilder(with_pip=True).create(directory)
    requirements = root / "requirements-core.txt"
    signature = hashlib.sha256(requirements.read_bytes()).hexdigest()
    marker = directory / ".maria-core-requirements"
    if not marker.is_file() or marker.read_text().strip() != signature:
        print("Installing core Python dependencies; this step needs Internet access...", flush=True)
        subprocess.run([str(executable), "-m", "pip", "install", "-r", str(requirements)], check=True)
        marker.write_text(signature + "\n")
    return executable


def new_config(path, model):
    """Exclusive creation: never replace configuration, including dangling links."""
    contents = (
        "# Created by scripts/start_chat.py. Keep this private.\n"
        f"MARIA_PIN={secrets.token_hex(4)}\n"
        f"MARIA_SECRET_KEY={secrets.token_hex(32)}\n"
        "MARIA_CHAT_BACKEND=ollama\n"
        f"MARIA_CHAT_MODEL={model}\n"
        "MARIA_HOST=127.0.0.1\n"
        "MARIA_RUNTIME_PROFILE=lean\n"
        "MARIA_BACKGROUND_REASONING=0\n"
        "MARIA_WARMUP=0\n"
        "MARIA_TELEGRAM_INTEGRATION=0\n"
        "MARIA_CONDUCTOR_INTEGRATION=0\n"
    )
    # Model names come from a CLI argument/server. They must not inject dotenv keys.
    if not model or any(char.isspace() or char in "#'\"\\=" for char in model):
        raise ValueError("Invalid model name")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        output.write(contents)


def chat_environment(config, model, url, port):
    result = {key: value for key, value in config.items() if value is not None}
    # This launcher always selects its explicit local chat profile, even when
    # the caller's shell or a preserved .env configures another backend.
    result.update({
        "MARIA_CHAT_ONLY": "1", "MARIA_CHAT_BACKEND": "ollama",
        "MARIA_CHAT_MODEL": model, "OLLAMA_HOST": url, "OLLAMA_BASE_URL": url,
        "MARIA_HOST": "127.0.0.1", "MARIA_PORT": str(port),
        "MARIA_DEBUG": "false", "MARIA_RUNTIME_PROFILE": "lean",
        "MARIA_BACKGROUND_REASONING": "0", "MARIA_WARMUP": "0",
        "MARIA_TELEGRAM_INTEGRATION": "0", "MARIA_CONDUCTOR_INTEGRATION": "0",
        "MARIA_CORS_ORIGINS": f"http://127.0.0.1:{port},http://localhost:{port}",
        "NO_PROXY": "localhost,127.0.0.1,::1", "no_proxy": "localhost,127.0.0.1,::1",
    })
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", help="Already installed Ollama chat model (default: .env or llama3.1:8b)")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--ollama-url", default="http://127.0.0.1:11434")
    parser.add_argument("--prepare-only", action="store_true", help="Prepare dependencies/config and check model availability without opening the UI")
    parser.add_argument("--prepared", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if sys.version_info < (3, 10):
        parser.error("Python 3.10 or newer is required")
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    url = local_url(args.ollama_url)
    try:
        installed = available_models(url)
    except Exception as exc:
        raise ValueError("Cannot read the local Ollama model list. Start Ollama, then retry; "
                         "see QUICKSTART.md. No model was downloaded.") from exc
    if not args.prepared:
        executable = ensure_environment(ROOT)
        command = [str(executable), str(Path(__file__).resolve()),
                   *(sys.argv[1:] if argv is None else argv), "--prepared"]
        if os.name == "posix":
            os.chdir(ROOT)
            os.execv(str(executable), command)
        return subprocess.call(command, cwd=ROOT)

    from dotenv import dotenv_values
    path = ROOT / ".env"
    if path.is_symlink():
        raise ValueError(".env is a symlink; use a separate clone with a regular private .env")
    config = dotenv_values(path, interpolate=False) if path.exists() else {}
    model = choose_model(args.model or config.get("MARIA_CHAT_MODEL") or "llama3.1:8b", installed)
    if not path.exists():
        new_config(path, model)
        config = dotenv_values(path, interpolate=False)
    if not (config.get("MARIA_PIN") or "").strip() or not (config.get("MARIA_SECRET_KEY") or "").strip():
        raise ValueError("Existing .env was preserved. Set non-empty MARIA_PIN and MARIA_SECRET_KEY "
                         "there before starting; see QUICKSTART.md.")
    if args.prepare_only:
        print("Core dependencies and login configuration ready. Model is listed by Ollama; "
              "inference has not been tested. Run again without --prepare-only to chat.")
        return 0

    with socket.socket() as check:
        try:
            check.bind(("127.0.0.1", args.port))
        except OSError as exc:
            raise ValueError(f"Port {args.port} is unavailable. Retry with --port 5050; "
                             "the running application was not stopped.") from exc
    os.environ.update(chat_environment(config, model, url, args.port))
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT))
    from maria_ui.app import app, socketio
    print(f"\nLocal chat: http://127.0.0.1:{args.port}", flush=True)
    print(f"Login PIN: {config['MARIA_PIN']}", flush=True)
    print(f"Model: {model}. History stays in this clone. Ctrl+C stops this UI.", flush=True)
    print("Chat only: no background learning, project execution or cloud-model routing.\n", flush=True)
    socketio.run(app, host="127.0.0.1", port=args.port, debug=False,
                 use_reloader=False, allow_unsafe_werkzeug=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print(f"Chat setup: {error}", file=sys.stderr)
        raise SystemExit(1)
