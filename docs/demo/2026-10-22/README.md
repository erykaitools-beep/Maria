# Maria: from context to action

[Full demo (MP4, 77 seconds)](maria-context-to-action-en.mp4) ·
[Animated preview](maria-demo-preview.gif) · [Still preview](maria-demo-poster.png)

Recorded on **22 October 2026**. The film combines a brief overview with one
completed task in the fictional **Lantern demo** project. It has English
editorial captions, the original Polish interface and replies, and no audio.
Waiting is shortened; product responses are unchanged. The animated preview
contains selected excerpts from the full film.

## What happens

| Time | Scene |
|---|---|
| 00:00 | Overview: conversation context, a continuing service, project work. |
| 00:05 | Earlier local-chat capture: context recovered after a demo-app restart. |
| 00:11 | Verified OS snapshot of Maria running on a miniPC. |
| 00:17 | Select a project and request a playtest checklist and results sheet. |
| 00:27 | Maria acknowledges the task; Kritaqo executes it. |
| 00:35 | Read the completed task report and open the saved file. |
| 00:44 | View the checklist, then the empty results sheet. |
| 01:02 | Ask Maria for the existing result using the explicit project name. |
| 01:09 | Try Maria. |

## Actual output

- [PLAYTEST.md](PLAYTEST.md): a checklist for the first ten minutes of a game,
  with three human players.
- [RESULTS.csv](RESULTS.csv): the results-sheet headers, with **zero result rows**.

One Kritaqo job completed and saved both files. The bytes returned through
Maria's artifact API matched the files on disk, including their size and SHA256.
The result question did not create another job or change the files. The human
playtest has not been performed; these files prepare for it.

The large checklist preview is an editorial formatting of the unchanged saved
file, following the real in-app file opening. It is not another product screen.
See [EVIDENCE.json](EVIDENCE.json) for the recording's provenance and
[SHA256SUMS.txt](SHA256SUMS.txt) for the media and generated-file checksums.

## Setup and limits

The task recording uses an isolated copy of Maria at public commit
[`918f0de`](https://github.com/erykaitools-beep/Maria/commit/918f0de73fcbb7f76f88b0cb42185f9fb61ab6e5),
with separately configured Kritaqo and authenticated OpenAI Codex
(`gpt-6.1-sol`). No existing user projects or conversations were used.

The earlier memory excerpt uses local Ollama (`qwen2.5:3b`) in a separate
installation. It shows restored conversation context, not perfect recall:
the recalled reply omitted the ten-minute detail. The service-status slide is
an editorial view of verified OS state from the running miniPC; background
reasoning was paused. It does not demonstrate active autonomous learning.

This is a selected successful workflow, not a reliability or speed benchmark.
An earlier request containing “do not perform the test” was routed as read-only
and produced chat text without a job. Explicit delegation succeeded. A generic
follow-up referring to “this project in two sentences” failed project routing;
using the project name read the recorded result. Those unsuccessful wording
trials are omitted from the short edit. Maria described an executor report,
not her own independent verification of file quality. Voice input and phone
operation are not tested in this recording.

## Try it

**[Start with the local-chat Quickstart](../../../QUICKSTART.md).** It uses
an existing Ollama model and does not enable project execution.

The demonstrated workflow requires additional configuration and compatible
deployment adapters that are not bundled in the public Maria or Kritaqo
repositories. See [voice and project integration requirements](../../VOICE_AND_PROJECTS.md)
before trying to reproduce that setup. This is not a fully offline,
single-command installation of the complete demo.
