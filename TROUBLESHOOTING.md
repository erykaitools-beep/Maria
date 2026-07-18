# Troubleshooting & FAQ

The questions a first-time Maria user actually hits, with concrete answers.
Setting up? Start with [QUICKSTART.md](QUICKSTART.md). Unsure what a word means?
See [GLOSSARY.md](GLOSSARY.md).

> Maintainers: this page is written so its body doubles as a README section —
> demote the headings one level and paste it under a `## Troubleshooting & FAQ`
> heading if you'd rather inline it.

## Is it working, or is it broken?

**This is the most important thing to understand.** Maria runs on your CPU with
no GPU, so she is *deliberately* slow: she thinks in minutes, not milliseconds.
Most "nothing is happening" moments are really "it's working, and slow."

Two fast ways to tell the difference:

- **Command line:** `python maria.py --check` verifies Python, `.env`, Ollama, and
  dependencies, and prints `[OK] All checks passed` or exactly what's wrong.
- **Dashboard:** open `http://localhost:5000`. If **Mode** is `ACTIVE`, the
  **tick count** rises every second, and **Health** sits near `1.0`, she's
  healthy — even if she hasn't produced visible output yet.

Rough timings that are **normal on CPU**: a chat reply in about a minute; a
dropped `.txt` becoming visible knowledge in 2–5 minutes; a one-time model
download of a few gigabytes at install.

## Install & first run

### `http://localhost:5000` refuses to connect

Check these in order:

1. **Did you answer the name prompt?** On the first run Maria asks your name *in
   the terminal*, and the Web UI does not start until you answer. Look at the
   terminal where you ran `python maria.py`.
2. **Is Ollama running?** Run `ollama list`. If it errors, the LLM runtime is
   down and the daemon can't fully start. Start it with `ollama serve` (or
   `sudo systemctl start ollama`) and restart Maria.
3. **Is port 5000 already in use?** Change `MARIA_PORT` in `.env` (e.g. `5050`)
   and restart, then browse to the new port.

### The model download is slow, failed, or ran out of disk

`install.sh` pulls `llama3.1:8b` (~5 GB), the longest step by far. If it fails
partway, simply re-run `bash install.sh` — Ollama resumes and skips finished
work. Confirm you have ~10 GB free with `df -h .`. To pull it by hand and watch
progress: `ollama pull llama3.1:8b`.

### Where is my Web UI PIN?

The installer wrote a random one into `.env`:

```bash
grep MARIA_PIN .env
```

Edit it to anything you like (minimum 6 characters) and restart Maria.

### The Web UI never appeared on my very first run

Expected. First-run onboarding runs in the terminal and **blocks** — Maria asks
your name and waits. Type a name, press Enter, and the Web UI starts a second
later. This only happens once.

## Learning & knowledge

### I dropped a `.txt` in `input/` and nothing happened

Usually "working, but slow." Check, in order:

1. **Give it time.** Expect minutes on CPU. Watch the knowledge counter on the
   dashboard, or the log lines streaming in the terminal.
2. **Does the folder exist?** `ls input/`. The `input/` folder is created at
   install time and isn't part of the cloned repo, so on a fresh checkout it may
   be missing — create it with `mkdir input` and drop your file in.
3. **Is it really a `.txt` with prose in it?** Maria only scans `.txt` files, and
   there needs to be actual text to extract knowledge from.

Your file stays in `input/` after learning — Maria tracks each file by a content
hash, so re-dropping identical text won't trigger re-learning.

### Semantic (meaning-based) search returns nothing

Meaning-based search needs the `nomic-embed-text` model. `install.sh` pulls it
automatically — but if you set Ollama up by hand, confirm it's present with
`ollama list | grep nomic-embed-text`. If missing, add it and restart:

```bash
ollama pull nomic-embed-text
```

Semantic results appear as Maria re-indexes existing knowledge.

## Running day to day

### How do I stop and restart Maria?

Press `Ctrl+C` in the terminal (or send `SIGTERM`) for a graceful shutdown. To
restart, run `python maria.py` again from the activated virtual environment.

### Where are the logs?

When you run `python maria.py` directly, logs stream to that terminal. When Maria
runs under systemd, they go to the journal: `journalctl -u maria -f`.

### Do I need Telegram, NVIDIA NIM, a camera, or internet?

No. The default local run needs none of them. Internet is only used *during
install* to download Ollama and the model; afterward Maria runs fully offline.
Telegram (chat + remote control), NIM (stronger cloud analysis), and the camera
(vision) are all optional and stay dormant unless you configure them in `.env`.
See [README.md → Configuration](README.md#configuration).

## Optional extras & development

### The systemd service won't start

`scripts/maria.service` ships as a **template** with placeholder paths. Before
installing it, edit the unit to match your setup:

- `User=` — replace `YOUR_USERNAME` with your Linux username
- `WorkingDirectory=`, `ExecStart=`, and `EnvironmentFile=` — replace
  `/absolute/path/to/Maria` with the absolute path where you cloned the repo

Then:

```bash
sudo cp scripts/maria.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now maria
sudo systemctl status maria    # confirm it's running
```

### Tests fail with import errors

You're almost certainly running them outside the virtual environment, or
dependencies aren't installed. From the repo root:

```bash
source venv/bin/activate
pip install -r requirements.txt
python -m pytest agent_core/tests/ -q
```

All tests are mocked — no network, no LLM, no external services required.

---

Still stuck? Open a [GitHub issue](https://github.com/erykaitools-beep/Maria/issues)
with what you expected, what happened, your Python version and OS, and the
relevant log lines.
