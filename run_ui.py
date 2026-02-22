#!/usr/bin/env python
"""
M.A.R.I.A. Web UI - Entry Point

Przed uruchomieniem zainstaluj zaleznosci:
    pip install flask flask-socketio simple-websocket psutil

Uruchom:
    python run_ui.py

Otworz w przegladarce:
    http://localhost:5000

Dostep z telefonu (ta sama siec WiFi):
    http://<IP_KOMPUTERA>:5000
"""

import os
from maria_ui.app import app, socketio
from maria_ui.config import DEBUG_MODE

if __name__ == '__main__':
    port = int(os.environ.get("MARIA_PORT", "5000"))
    host = os.environ.get("MARIA_HOST", "0.0.0.0")

    print("=" * 50)
    print("[START] M.A.R.I.A. Web UI")
    print("=" * 50)
    print()
    print("Upewnij sie ze Ollama dziala (ollama serve)")
    print()
    print(f"Otworz w przegladarce: http://localhost:{port}")
    print("Ctrl+C aby zatrzymac")
    print("=" * 50)

    socketio.run(
        app,
        host=host,
        port=port,
        debug=DEBUG_MODE,
        allow_unsafe_werkzeug=DEBUG_MODE
    )
