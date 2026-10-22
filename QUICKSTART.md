# Quick start: local chat

Start with a browser conversation using an **already installed local Ollama
chat model**. This path needs no cloud-model account. It does not start the
learning daemon, run project work, or configure voice.

This setup targets **Linux with Python 3.10+**. macOS and Windows have not been
validated for this launcher. Model memory and disk requirements depend on the
model you choose; no GPU is required by Maria's chat interface.

The browser interface is currently in Polish and loads its Socket.IO JavaScript
from a CDN. A local model does not make that first browser load fully offline.

## 1. Prepare Python and Ollama

You need Python with `venv`/`ensurepip` support, Git, and a running
[Ollama installation](https://ollama.com/download). On Ubuntu/Debian, missing
Python setup tools can be installed deliberately with:

```bash
sudo apt install python3 python3-venv git
```

Install and start Ollama using its instructions. Then inspect your models:

```bash
ollama list
```

Choose an installed **chat** model, not an embedding-only model. The following
example uses `llama3.1:8b`. If you want that model and it is not installed,
download it explicitly:

```bash
ollama pull llama3.1:8b
```

That command downloads model weights and needs Internet access and sufficient
free disk space. The Maria launcher never installs or starts Ollama, downloads
models, or selects another model silently. You may instead use another chat
model from your `ollama list` with `--model NAME`.

## 2. Start the chat

```bash
git clone https://github.com/erykaitools-beep/Maria.git
cd Maria
python3 scripts/start_chat.py --model llama3.1:8b
```

On the first run, the launcher creates **`.venv-chat`**, installs
`requirements-core.txt`, and creates a private **`.env`** only if none exists.
Dependency installation needs Internet access. The new configuration contains a
random login PIN and a persistent session key. Neither the virtual environment
activation command nor a terminal name prompt is needed.

Open **http://127.0.0.1:5000**, enter the **Login PIN** printed in the terminal,
and type a message. The model is called when you send a message; listing the
model or opening the page does not demonstrate successful inference. Keep the
terminal running. **Ctrl+C stops this chat process.**

For the next session, run the same `python3 scripts/start_chat.py --model ...`
command from this clone. The launcher reuses the environment and configuration;
changed core requirements may trigger dependency installation again.

## What this mode does

- Uses the explicitly selected local Ollama backend and listens on
  **127.0.0.1 only**, with debugging and the reloader disabled.
- Keeps browser chat history and durable request receipts in `maria_ui/data/`.
  Conversation memory and operator-related state also use `meta_data/`.
  Preserve **both directories and `.env`** when keeping or backing up this
  installation. These contain private data and do not belong in a public commit.
- Does not start autonomous background reasoning, learning, Telegram, conductor
  work, cloud-model routing, or Kritaqo project execution. You can discuss plans;
  a chat response is not evidence that a task ran on another computer.

An existing `.env` is not overwritten. The launcher nevertheless selects its
local chat profile **for this process**, even if that file or your shell selects
another backend or background mode. It does not stop another Maria process,
change its settings, or cancel work already running elsewhere. Use a separate
clone to try the quick start beside an existing installation.

## Options and troubleshooting

### Check preparation without opening the UI

```bash
python3 scripts/start_chat.py --model llama3.1:8b --prepare-only
```

This can install Python dependencies and create `.env`. It checks that Ollama
lists the model, then exits. **It does not invoke the model or prove that chat
inference works.** Run again without `--prepare-only` to open the chat process.

### Port 5000 is already in use

Choose another port; the launcher does not stop the existing program:

```bash
python3 scripts/start_chat.py --model llama3.1:8b --port 5050
```

Open the local URL printed by the launcher.

### Ollama is not responding or uses another local port

Start Ollama separately and check `ollama list`. The default server URL is
`http://127.0.0.1:11434`. For a different **loopback** endpoint:

```bash
python3 scripts/start_chat.py --model llama3.1:8b --ollama-url http://127.0.0.1:11435
```

Only local HTTP Ollama URLs are accepted. A missing model produces an explicit
error; choose an installed model or download one yourself.

### Python cannot create the environment

Install the matching Python `venv`/`ensurepip` support for your distribution,
then retry. Do not run the launcher with `sudo`. If a dependency installation
fails, keep the error output and retry after addressing it; do not treat that as
a completed setup.

### Existing configuration has a blank PIN or session key

The launcher preserves `.env` and refuses to start when `MARIA_PIN` or
`MARIA_SECRET_KEY` is blank. Set a private nonempty PIN and a randomly generated
session key in that file, or use a fresh clone for a clean setup. A key can be
generated locally with Python's `secrets.token_hex(32)`; never publish it.
Changing an established session key invalidates existing browser sessions.
Symlinked `.env` files are not supported by this quick-start launcher.

## Optional voice and project integrations

The local text chat is the starting point, not an automatic installation of
all integrations. Browser microphone use from a phone needs a reachable trusted
HTTPS origin, a separately installed whisper.cpp binary/model, and explicit
origin configuration. The loopback address above is not a phone-access URL.
Optional Kritaqo project tools require its separate installation, bridge and
existing project permissions; they stay disabled in this chat-only launcher.
Codex chat likewise needs a separate compatible authenticated installation and
is not selected by this launcher.

See [Voice, conversation, and project work](docs/VOICE_AND_PROJECTS.md) for those
separate paths and their limits. No Docker deployment is supplied by this guide.

## Advanced: the full daemon

The full runtime includes the homeostasis loop and optional learning, perception
and integrations. It is a separate setup, not required for local chat. Read
[README](README.md), the configuration template and **`install.sh` before running
it**: the legacy installer can install/start Ollama, download both chat and
embedding models, and install the full Python dependency set, including optional
vision and test packages.

For an installation you have reviewed:

```bash
bash install.sh
source venv/bin/activate
python maria.py
```

Review `.env` and explicitly choose which background features to enable. The
first daemon run may ask your name in the terminal. Its behavior and readiness
checks differ from the chat-only launcher; a visible web page is not proof that
learning, models or external project execution work. Do not use the legacy
installer as an unreviewed upgrade command for an existing deployment.
