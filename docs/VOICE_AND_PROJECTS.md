# Voice, conversation, and project work

This guide describes the October 2026 browser interface and optional project
integration. Configure external runtimes and access for your own installation;
no model files, credentials, device addresses, or project grants are bundled.

## Chat and operator-first operation

| Variable | Purpose |
|---|---|
| `MARIA_CHAT_BACKEND` | `ollama` (default) or `codex`. |
| `MARIA_CHAT_MODEL` | Selected Ollama chat model. |
| `MARIA_CODEX_MODEL` | Selected Codex model; it must be available to your account. |
| `CODEX_BIN` | Optional Codex executable override; otherwise resolved from `PATH`. |
| `MARIA_RUNTIME_PROFILE` | `standard` (default) or `lean`; lean shortens model residency. |
| `MARIA_BACKGROUND_REASONING` | `0` pauses background reasoning and associated model startup work; default `1`. |
| `MARIA_WARMUP` | `0` disables model warmup. |
| `MARIA_TELEGRAM_INTEGRATION` | `0` skips Telegram initialization, polling, and notifications; default `1`. |
| `MARIA_CONDUCTOR_INTEGRATION` | Controls the generic conductor; default off in `lean`, on in `standard`. |

Lean residency and background-reasoning admission are independent. For
interactive operation, explicitly disabling background reasoning, warmup, and
Telegram keeps conversation and stored memory available while reducing
background model activity. Perception and already admitted deterministic actions
can still run. This is not a guarantee of zero network activity or a cancellation
of previously authorized work on other systems.

The optional Codex backend requires a compatible, authenticated external Codex
installation. Maria does not supply account credentials. It passes Maria's
identity and conversation context to the selected chat backend; a backend change
does not replace that identity or grant new tools. The selected model is taken
from the actual backend instance, not guessed from the conversation. This is a
selection descriptor, not independent proof of the model executed by a provider.

A configured Codex chat failure is reported without silently switching the turn
to Ollama. The conversation path does not inherit unrestricted shell or MCP
access. Interactive project tools require their configured providers and trusted
turn context; structured/background calls do not gain them merely by selecting
Codex for chat.

## Local speech recognition

Install a compatible **whisper.cpp `whisper-cli`** and model separately, then
configure absolute paths. The implemented endpoint transcribes Polish using the
CLI's JSON output contract.

```dotenv
MARIA_STT_BIN=/absolute/path/to/whisper-cli
MARIA_STT_MODEL=/absolute/path/to/whisper-model.bin
MARIA_STT_ORIGINS=https://assistant.example.test
```

These are example paths and an example origin, not installation defaults.
`MARIA_STT_ORIGINS` adds exact allowed origins to the application's existing
origin configuration. Use your actual scheme, hostname, and port, without a
wildcard. This setting does not install HTTPS or trust a certificate on a phone.
Authenticated `GET /api/voice/status` reports recognizer availability.

The browser converts microphone audio to mono 16 kHz PCM16 WAV and uploads a
bounded utterance to `POST /api/voice/transcribe`. Recognition runs on the
configured whisper.cpp host. Audio is temporarily materialized for the process
and cleaned up; this is not a permanent recording feature. Chat text is retained
in the normal conversation history.

The endpoint accepts at most **30 seconds / 1 MiB**, with one transcription at a
time, a default **45-second timeout**, and six attempts per minute. Busy,
unavailable, invalid-audio, and timeout responses are failures, not a switch to
Apple recognition.

**ffmpeg is not called by this WAV-based endpoint.** It can help prepare or
convert external test audio, but installing it alone does not configure Maria's
recognizer. There is no ffmpeg executable setting for this path.

## Foreground conversation

1. Open the page over a secure origin trusted by your browser, log in, and keep
   it visible. Remote microphone access generally requires HTTPS.
2. Select **Rozmowa: Maria** and allow microphone access. A startup voice cue
   precedes listening.
3. Say **“Maria, jakie projekty mamy?”**, then leave about **four seconds of
   audio silence**. There is no second four-second text timer after transcription.
4. After an accepted turn, continue with **“A jaki jest następny krok w wybranym
   projekcie?”** without repeating the name.

“Maria” or “Mario” alone opens the conversation with an acknowledgment and no
model request. After **three minutes of idle listening**, it returns to waiting
for the name. Transcription, model processing, and playback do not consume that
listening budget. **“Koniec rozmowy”** returns to standby; **Stop** ends voice
conversation.

The wake word is recognized in transcribed speech; it is not a separate keyword
detector. This is foreground interaction, without a promise of listening through
a locked phone, suspended tab, or operating-system background restriction. The
microphone pauses during response generation and playback. Stop, hiding the
page, disconnecting, typing a draft, or changing project can invalidate ongoing
voice work. Interrupted or over-limit recordings must not dispatch truncated
requests.

**Mów** dictates into the text field for inspection before sending.
**Sprawdź mikrofon** is a separate short input-level probe; measured signal does
not prove transcription works. Native keyboard dictation belongs to the device
OS and has its own processing/privacy behavior.

The legacy browser SpeechRecognition path is distinct and may use vendor
services. A microphone icon alone is not evidence of local processing. When the
configured local path is unavailable, the UI does not silently switch to
vendor-service recognition.

## Short speech, complete persistent text

Automatic speech prefers a bounded **`## W skrócie`** section before
**`## Pełny raport`**. A short whole response can be read in full. If a long reply
has no valid short section, it reads a clearly labeled bounded beginning or asks
you to use the full readout; clipping is not presented as a semantic summary.
The automatic budget is up to three sentences and 70 words.

The full reply remains in chat and can be restored after reload. Use
**Odsłuchaj całość** for explicit full playback. **Przerwij odczyt** interrupts
speech and resumes listening only when an existing conversation remains eligible.
Stop ends conversation. Restored history and recovered replies do not autoplay.
Available system/browser voices determine speech playback; server tests do not
prove a Polish voice or successful sound output on a physical device.

## Shared projects and new work

Kritaqo ([source repository](https://github.com/erykaitools-beep/kritaqo)) is an external application and permission authority, not an embedded
server in this repository. Configure its bridge and existing shared-host grants
first. `MARIA_KRITAQO_TOOLS_CONFIG` points to a private JSON configuration with
data, bridge, and receipt directory paths plus legacy target identity fields.
Keep installation credentials and project data outside public examples.

The adapter files described below are deployment additions; they are not bundled
in this Maria snapshot or the current public Kritaqo main snapshot. Cloning both
repositories alone does not enable project tools. Until compatible adapters are
installed and configured, that integration remains unavailable.

The current configuration schema requires all of these fields. The values below
are illustrative: obtain identities and the workspace revision from your own
paired installation, and use canonical absolute paths. Do not guess a revision
or copy someone else's grants. The legacy pinned target is still required when
initializing the combined provider; the generic panel selection is validated
separately.

```json
{
  "data_dir": "/srv/kritaqo/data",
  "bridge_path": "/opt/kritaqo/maria_bridge.py",
  "state_dir": "/srv/maria/kritaqo-receipts",
  "peer_id": "example-peer",
  "host_node_id": "example-host",
  "project_id": "example-project",
  "workspace_revision": 1,
  "project_name": "Roblox",
  "computer_name": "Laptop"
}
```

Create the parent of `state_dir` first. The receipt directory must belong to the
Maria process user and have mode `0700`. Keep the configuration owner-controlled
and non-writable by group/others (for example `0600`), then set its absolute
filename in `MARIA_KRITAQO_TOOLS_CONFIG`. The installed Python bridge must provide
the expected peer/project contract, with compatible Node bridge files beside it;
this JSON alone does not install a connector. The server integration uses POSIX
file locking and expects Node at `/usr/bin/node`.

The generic work service uses the bridge's `work_bridge.mjs` sibling. It lists
the configured local host and registered shared projects, validates host/project
identity and applicable workspace revision, and honors existing grants. It does
not discover arbitrary computers, grant itself access, or bind arbitrary folders.
Older hosts may expose reports without supporting artifact reads.

- **Choose a project and computer in the panel.** Identical project names on
  different hosts are separate targets. Wait for confirmation before sending.
  Selection persists and is shared by this installation's operator interface.
- **Read existing results:** “Odczytaj ostatni wynik tego projektu i podaj jeden
  następny krok. Nie uruchamiaj nowej pracy.” Refreshing lists or selecting a
  project does not submit an analysis.
- **Review the portfolio:** ask for shared-project status. Coverage may be
  partial, offline, cached, or unknown; a history overview is not a file inspection.
- **Explicitly request new work.** Read-only portfolio analysis has a constrained
  execution path. Ordinary file work needs the selected target, current permission,
  and an explicit request; it can change files within its admitted scope. Read-only
  analysis still uses a model and is not the same operation as reading a report.
- **Ask about completion or open the card later.** Do not repeat the original
  task merely to retrieve its result.

Model arguments cannot authorize another target. Unknown, altered, or ambiguous
project/host names require a selection instead of sending work to the previous
target. The original operator request and resolved target are fixed for a turn;
not every natural-language spelling is understood.

The interactive model tool-calling integration currently uses the optional Codex
chat backend. The panel's authenticated project/result reads are separate from
that model path; selecting Ollama does not by itself add equivalent tool calling.

## Receipts and evidence

Chat requests carry a durable ID. Missing outcomes are reconciled against the
receipt endpoint without automatically sending the message again. A restart
can leave a pending outcome **unknown**. Check history and task cards before
explicitly allowing a new turn: a new request can still create additional work.

Project work records its request identity before dispatch. The observer reads
only known submissions, without model calls or automatic resubmission. Reports
and a completion event are persisted. Historical jobs establish a baseline,
not a notification storm. This does not promise push delivery to a closed app
or an offline phone.

| Displayed state | Meaning |
|---|---|
| Accepted / queued / running | The executor has not reported completion. |
| Completed | An executor report, not independent artifact or human-test verification. |
| Unknown / stale / unavailable | Keep the last known report and date; do not infer success or automatically resend. |
| Current recorded check | Server-projected currency of a verification record and artifact hashes, with its stated limitations. |
| Stale / unknown check | Explain the recorded reason rather than silently promoting it or repeating completed checks. |

Current passed records take precedence over older model reports listing the
same check as unfinished. A user may explicitly request a new analysis; a model
report's recommendation is not authorization to execute it.

Artifacts require an explicit click and a job-scoped allowlist. Reads are bounded
to **1 MiB**, with scope/path validation and available integrity metadata. Text,
CSV, Markdown, and JSON are displayed as text; HTML is not executed as a preview.
Unavailable files and unsupported hosts are reported without pretending files
were inspected.

## Publication and device limits

This snapshot contains the Maria side of the integration. External Codex,
whisper.cpp, and Kritaqo installations require separate setup. Runtime credentials,
models, private data, and device addresses are excluded.

A separate Android client has a prepared 1.1 release; its sources and APK are
not included here. Physical Android microphone/TTS acceptance is still pending.
Mocked controllers or an APK build are not physical-device evidence. No end-to-end
voice latency benchmark is claimed for either client.
