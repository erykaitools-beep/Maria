# Quick Start — Maria in 10 minutes

This is the honest, no-shortcuts path from a fresh clone to a running Maria you
can watch learn. No Telegram, no cloud API, no account — just your machine and a
local LLM.

New to the vocabulary (daemon, tick loop, belief, mode, K1–K13)? Keep
[GLOSSARY.md](GLOSSARY.md) open in another tab. If something breaks, jump to
[Troubleshooting](#troubleshooting) at the bottom or [TROUBLESHOOTING.md](TROUBLESHOOTING.md).

## One honest heads-up first

Maria runs entirely on your CPU (no GPU required). That has one consequence you
should expect from the start: **she thinks in minutes, not milliseconds.** The
one-time model download is a few gigabytes, learning a file takes several
minutes, and a chat reply lands in roughly a minute. This is normal. Most
"nothing is happening" moments are really "it's working, and slow." The steps
below tell you exactly what a healthy, working system looks like at each stage so
you can tell the difference.

## Before you start

| You need | Details |
|----------|---------|
| **OS** | Linux (Ubuntu 22.04+ recommended) or macOS |
| **Python** | 3.10 or newer (`python3 --version`) |
| **RAM** | 16 GB recommended (8 GB works, slower) |
| **Disk** | ~10 GB free (the local LLM is ~5 GB) |
| **Internet** | Only for install (download Ollama + the model). Maria runs offline afterward. |
| **Time** | ~10 minutes on a decent connection. The `llama3.1:8b` model download dominates — budget more on slow links. |

You do **not** need a Telegram bot, an NVIDIA NIM key, a camera, or any API key.
Those are all optional add-ons ([README](README.md) covers them). This guide is
the minimal local run.

## Step 1 — Get the code

```bash
git clone https://github.com/erykaitools-beep/Maria.git
cd Maria
```

## Step 2 — Run the installer

```bash
bash install.sh
```

The script is a 7-step guided setup. It checks your system, installs
[Ollama](https://ollama.com) (the local LLM runtime), pulls the `llama3.1:8b`
model (~5 GB — this is the slow part) plus the small `nomic-embed-text` embedding
model, creates a Python virtual environment, installs dependencies, and generates
a `.env` config with a random Web UI PIN.

**What you'll see:** step-by-step `[1/7] … [7/7]` progress, then a green
`Installation complete!` banner. Near the end it prints your generated PIN:

```
  .env: created from template
  Web UI PIN: a1b2c3d4 (change in .env if needed)
```

Write that PIN down — you'll need it in Step 4. (You can always find it again;
see Troubleshooting.)

> If the model download stalls or fails, that's the most common install hiccup —
> see [Troubleshooting](#troubleshooting). Everything else in the script is fast.

## Step 3 — Start Maria

```bash
source venv/bin/activate
python maria.py
```

**Answer the name prompt in the terminal first.** On the very first run Maria
introduces herself and asks your name *in the terminal*. This is her onboarding,
and it blocks until you answer — the Web UI does **not** start until you do.
Type a name and press Enter.

**What you'll see** after that: a startup banner with your RAM, CPU cores, and
detected Ollama models, then:

```
  Web UI:   http://localhost:5000
  Daemon:   homeostasis tick loop (1Hz)
  Stop:     Ctrl+C or SIGTERM
```

The terminal keeps streaming log lines from here on — that's the daemon ticking
once per second. Leave it running.

## Step 4 — Open the dashboard

Open **http://localhost:5000** in your browser and enter the PIN from Step 2.

**What you'll see:** the Status Dashboard. The signs that Maria is alive and
healthy:

- **Mode** reads `ACTIVE` (she drops to `REDUCED`, `SLEEP`, or `SURVIVAL` only
  under load or idle — see [GLOSSARY.md](GLOSSARY.md))
- **Health** is a score near `1.0`
- The **tick count** climbs every second
- Knowledge / beliefs / goals counters are shown (they may start near zero on a
  fresh install — that's expected)

If the dashboard loads and the tick count is rising, you have a working Maria.

## Step 5 — Give her something to learn

Maria learns from plain-text files you drop into the `input/` folder. The
installer created it; drop a `.txt` in and she picks it up automatically on her
next planner cycle (about a minute).

```bash
echo "The Great Barrier Reef is the world's largest coral reef system,
composed of over 2,900 individual reefs off the coast of Queensland, Australia." > input/reef.txt
```

Or copy any notes you already have:

```bash
cp ~/my_notes.txt input/
```

**What you'll see:** nothing instant — this is the CPU-is-slow moment. Within a
minute or two the planner scans `input/`, then over the next several minutes
Maria chunks the file, calls the local LLM to extract knowledge, and writes it to
her knowledge index. The **knowledge counter on the dashboard ticks up** once
extraction finishes. Your file stays in `input/`; Maria tracks its progress by
content hash, so re-dropping the same text won't re-learn it.

> Patience check: on CPU, one small file becoming visible knowledge in
> 2–5 minutes is normal. If it's been much longer, see Troubleshooting.

## Confirm it's alive

Any time you want a fast, no-browser health check, run:

```bash
python maria.py --check
```

It verifies Python, your `.env`, Ollama connectivity, and the key Python
dependencies, then prints `[OK] All checks passed` (exit code 0) or lists exactly
what's wrong (exit code 1). This is the quickest way to answer "is my
environment set up correctly?"

## What "healthy" looks like — recap

| Signal | Healthy value |
|--------|---------------|
| `python maria.py --check` | `[OK] All checks passed` |
| Dashboard **Mode** | `ACTIVE` |
| Dashboard **tick count** | rising every second |
| **Health** score | near `1.0` |
| Dropped a `.txt` | knowledge counter rises within a few minutes |
| Chat reply latency | ~1 minute on CPU (up to a few minutes when busy) |

## Where to go next

- **Vocabulary:** [GLOSSARY.md](GLOSSARY.md) — every term above, in plain language
- **The full picture:** [README.md](README.md) — features, architecture, production notes
- **Optional Telegram bot / NIM analysis:** [README.md → Configuration](README.md#configuration)
- **How her mind is structured:** [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and [docs/CONTRACTS.md](docs/CONTRACTS.md)
- **Run the tests:** `python -m pytest agent_core/tests/ -q`

---

## Troubleshooting

The five things most likely to trip up a first run. For a fuller FAQ, see
[TROUBLESHOOTING.md](TROUBLESHOOTING.md).

### `http://localhost:5000` refuses to connect

Usually one of three things:

1. **You haven't answered the name prompt yet.** On first run the Web UI only
   starts *after* you type your name in the terminal (Step 3). Check the terminal.
2. **Ollama isn't running,** so the daemon couldn't finish starting. Confirm with
   `ollama list`. If it errors, start Ollama: `ollama serve` (or
   `sudo systemctl start ollama`), then restart `python maria.py`.
3. **Port 5000 is taken** by another program. Change it in `.env`
   (`MARIA_PORT=5050`), then restart. Run `python maria.py --check` to confirm
   the rest of the environment is fine.

### The model download is slow, failed, or ran out of disk

`install.sh` pulls `llama3.1:8b` (~5 GB) — the longest step. If it fails midway,
just re-run `bash install.sh`; Ollama resumes the download and skips work already
done. Make sure you have ~10 GB free (`df -h .`). To pull manually and watch
progress: `ollama pull llama3.1:8b`.

### I can't find my Web UI PIN

It's stored in the `.env` file the installer created:

```bash
grep MARIA_PIN .env
```

Change it to anything you like (min 6 characters) and restart Maria.

### I dropped a `.txt` in `input/` and nothing happened

Almost always "working, but slow." Check, in order:

1. Give it time — expect **minutes on CPU**, not seconds. Watch the knowledge
   counter on the dashboard, or the log lines in the terminal.
2. Confirm the folder exists and the file is really there:
   `ls input/`. If `input/` is missing (it's created at install and isn't part of
   the cloned repo), make it: `mkdir input`.
3. Confirm the file ends in `.txt` and contains real prose — Maria only scans
   `.txt` files.

### Semantic (meaning-based) search returns nothing

Meaning-based search needs the `nomic-embed-text` model. `install.sh` pulls it
for you — but if you set Ollama up by hand, confirm it's present:

```bash
ollama list | grep nomic-embed-text
```

If it's missing, add it and restart Maria; results appear as she re-indexes:

```bash
ollama pull nomic-embed-text
```
