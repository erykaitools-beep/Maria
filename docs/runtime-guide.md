# Runtime guide and implementation status

[Portfolio README](../README.md) · [Quickstart](../QUICKSTART.md)
· [Reliability case study](production-reliability-case-study.md) · [Documentation map](README.md)

M.A.R.I.A. expands to Meta Analysis Recalibration Intelligence Architecture.

Reviewed against public revision `47eaec0` on 26 October 2026. This guide keeps
the operational detail and screenshots previously embedded in the root README.

## Choose a runtime

| Path | Implemented behavior | Setup boundary |
|---|---|---|
| Local text chat | Browser conversation, persistent context and request receipts, selected Ollama model | [Quickstart](../QUICKSTART.md); Linux/Python, existing Ollama and installed chat model. |
| Full daemon | Control loop, tactical planner, persistence, health monitoring, configured background actions | Review [install.sh](../install.sh), [.env.example](../.env.example) and the [advanced setup](../QUICKSTART.md#advanced-the-full-daemon). |
| Voice and vision | Browser voice handling, external local speech recognition, optional camera processing | Separate binaries/models, device permissions and configuration; [interaction guide](VOICE_AND_PROJECTS.md). |
| Telegram | Commands, approvals and configured notifications | A bot and private credentials, plus the integration enabled in the daemon. |
| External project work | Project selection, explicit work requests, receipts and saved reports | Compatible Kritaqo/Codex services and deployment adapters; the public clone alone is insufficient. |

The local-chat launcher overrides backend and background settings for its own
process and preserves an existing `.env`. It does not stop other processes or
cancel previously authorized work elsewhere. The full daemon is a separate
setup: its legacy installer can install/start Ollama, download models and install
optional packages. Review it before execution and use a separate clone beside an
existing deployment.

`lean` is a model-residency policy, not an off switch for background reasoning.
Before using the full daemon, review `MARIA_BACKGROUND_REASONING`, `MARIA_WARMUP`,
`MARIA_TELEGRAM_INTEGRATION` and `MARIA_CONDUCTOR_INTEGRATION`.

## Implemented, experimental and planned

| Status | Examples | What the status establishes |
|---|---|---|
| Implemented in public code and covered by tests | Local chat, request identity/recovery, state stores, deterministic planning, action policies, workflow scheduling, traces, resource coordinator | The paths exist; their configured deployment and real-model outcomes require separate checks. |
| Implemented, separately configured | Autonomous learning, Telegram, camera processing, browser voice, cloud model backends and project delegation | These are not all enabled by the local-chat Quickstart. |
| Library or experiment | Procedural [skills](../agent_core/skills/__init__.py), [symbolic](../agent_core/symbolic/__init__.py) and [predictive](../agent_core/predictive/__init__.py) research | Presence in the tree does not establish integration into the daemon or an autonomous capability. |
| Planned or acceptance work remains | Smart-home rollout, complete procedural-skill wiring, full demo setup from public dependencies alone, physical phone/voice acceptance | No completed product claim. Historical roadmaps describe intended work. |

Self-repair is a detection and operator-acknowledgement workflow. It does not
mean autonomous code repair. Experiment promotion recommendations also require
their configured approval path; a proposed improvement is not a verified gain.

## Configuration and persistence

| Setting | Purpose |
|---|---|
| `MARIA_PIN`, `MARIA_SECRET_KEY` | Private UI access and persistent session configuration. The first-run launcher generates these when creating `.env`. |
| `OLLAMA_BASE_URL` | Full-runtime Ollama endpoint; the chat launcher has an explicit local `--ollama-url` option. |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | Optional bot credentials and destination. Keep them out of commits and screenshots. |
| `NVIDIA_NIM_API_KEY` | Optional external model service credential; not needed for the local-chat path. |

For Telegram setup, create a bot through [BotFather](https://t.me/BotFather),
obtain the intended chat ID, and configure the integration privately. Existing
commands include `/status`, `/goals`, `/approve`, `/reject`, `/learn`, `/remind`
and `/help`; availability depends on the runtime wiring. Notification scheduling
includes quiet periods and per-reason cooldowns. Configuration changes must be
applied through the deployment's own maintenance procedure.

Preserve `.env`, `maria_ui/data/` and `meta_data/` for the chat profile. The full
learning runtime additionally writes knowledge under `memory/` and consumes
`input/`; retain the stores used by that configuration. Generated data is private.
JSON/JSONL stores and SQLite chat receipts have different persistence semantics.
The older [persistence inventory](PERSISTENCE_CONTRACT.md) is historical, not an
assertion that every current write is atomic.

## Full-daemon operation

The [service unit](../scripts/maria.service) is an editable template with
`Restart=on-failure`. Set its account and paths for your installation and review
resource controls before enabling it. The operator-host memory limits described
in the portfolio audit are additional deployment configuration, not defaults
supplied by this template. A separate Ollama service needs its own resource plan.

The control loop regulates `ACTIVE`, `REDUCED`, `SLEEP` and `SURVIVAL` modes.
Configured text learning follows source ingestion, chunking, model extraction,
persistence and later examinations. Adding a text file to `input/` does not
start learning in chat-only mode. A health label or a growing tick counter is
not evidence that an external action succeeded.

Persistent task and chat records distinguish requests, in-progress work,
recorded results and uncertain outcomes. Read results before repeating work;
the receipt mechanism deliberately avoids blindly resending an uncertain chat
request after a restart.

## Source map

| Area | Entry point |
|---|---|
| Launcher and shutdown | [maria.py](../maria.py) |
| Scheduling, watchdog and off-tick work | [homeostasis/core.py](../agent_core/homeostasis/core.py) |
| Tactical decisions and stale-goal cleanup | [planner_core.py](../agent_core/planner/planner_core.py) |
| Model roles and residency | [model_registry.py](../agent_core/llm/model_registry.py), [model_scheduler.py](../agent_core/llm/model_scheduler.py) |
| Local compute arbitration | [local_compute.py](../agent_core/llm/local_compute.py) |
| Persistent chat request identity | [chat_turns.py](../maria_ui/chat_turns.py) |
| Tests and automation | [agent_core/tests](../agent_core/tests/), [CI workflow](../.github/workflows/test.yml) |

K1–K13 group perception (K1), sandbox boundaries (K2), goals/planning (K3/K5/K8),
evaluation (K4), beliefs/reflection (K6/K9), policy/audit (K7/K10), and
experiments/analysis/proposals (K11–K13). The [contracts](CONTRACTS.md) retain the
original design details; active behavior must be checked against code.

## Screenshots

These retained screenshots show earlier UI states. They are navigation aids,
not current deployment or performance evidence. The
[dated video and its notes](demo/2026-10-22/README.md) describe the recorded flow.

![Status dashboard: health, mode, goals and knowledge](https://github.com/user-attachments/assets/bfca558d-33df-4abc-ba71-1d373ed1022e)

![Extended dashboard: planner, experiments and model registry](https://github.com/user-attachments/assets/f3840380-0830-4624-8aae-d97175fce977)

![Decision traces grouped by episode](https://github.com/user-attachments/assets/75afda18-9c92-4488-a108-a13687d18ecc)

The separately maintained Flutter Android client is not included here. A
successful client build or mocked test is not physical microphone/TTS acceptance.
