# Portfolio evidence audit — 26 October 2026

[Portfolio README](../../README.md) · [Case study](../production-reliability-case-study.md)
· [Machine-readable evidence](portfolio-audit-2026-10-26.json)

## Scope and method

This documentation review starts from public commit
[`47eaec0bed17ec18b431ea4eb769aa6b91676a9e`](https://github.com/erykaitools-beep/Maria/commit/47eaec0bed17ec18b431ea4eb769aa6b91676a9e),
not the private development branch. Its application code and existing demo were
kept unchanged. The private operator host was inspected read-only. No model was
invoked and no service was stopped or restarted for the audit.

Evidence types are kept separate: public code establishes implementation;
executed tests establish tested behavior; the selected recording establishes its
shown workflow; the host observation describes one installation at one time.
None of these alone establishes a service-wide availability or task-success rate.
The JSON receipt records observation dates, test counts, source symbols and
reproduction methods without credentials, device addresses or private log text.

## Tests

[Public run 39823011497](https://github.com/erykaitools-beep/Maria/actions/runs/39823011497)
completed successfully on **22 October 2026** for this exact revision. The job
API and the individual log summaries were checked on 26 October.

| Job | Result from its log |
|---|---|
| Python 3.10 | 8,164 passed; 4 skipped; 1 xpassed; 140 passing subtests; 1 warning |
| Python 3.11 | 8,164 passed; 4 skipped; 1 xpassed; 140 passing subtests; 1 warning |
| Python 3.12 | 8,164 passed; 4 skipped; 1 xpassed; 140 passing subtests; 123 warnings |
| Minimal local chat | 24 passed; 16 passing subtests |
| Node step in each Python job | 3 passed; 0 failed |

These are overlapping jobs, not additive unique-test counts. An `xpassed` test
was marked as expected to fail but passed under the run's conditions. Green CI
must not hide it or the warnings. Requirements currently use version ranges;
reinstalling later may select different dependencies.

Two bounded local selections on **26 October** reported **254 passed, 1 skipped,
16 passing subtests**, then **32 passed**. The skip requires the intentionally
untracked `CLAUDE.md`; no such private instruction file was added. The selections
cover first-run chat, timeout and shutdown behavior, goal cleanup, workflow,
world-model stores/building/confidence, and documentation checks. The second
selection explicitly covers `test_core.py::TestWorkflowPhaseOffTick` and
`test_freeze_hardening_20260602.py`.

They ran in an isolated public checkout with temporary test state and a cleared
environment. Parent network connections were denied; the first-chat subprocess
used its loopback fixture and its own network/process guards. A separate
watchdog subprocess check asserted the exact diagnostic and exit status with
this checkout on `PYTHONPATH`, guarding against an import error masquerading as
a successful hard-exit test. Public CI independently exercises the selected
regressions. No complete local suite rerun or real-provider acceptance is claimed.

## Host and source measurements

The CPU name was checked through `lscpu` and `/proc/cpuinfo`; the memory report
agreed with `/proc/meminfo`. The OS exposes **33,039,904,768 bytes (30.77 GiB)**
on the documented 32 GB host. PCI enumeration listed an integrated AMD Barcelo
display controller and no discrete graphics controller. This is an inventory
observation, not a throughput benchmark or proof of which device every model
request used.

systemd reported the Maria service active/running. Its process existed, and the
bounded journal sample contained records from that process. This establishes
process activity, not successful reasoning. `MemoryHigh=16G` and `MemoryMax=20G`
matched cgroup `memory.high=17179869184` and `memory.max=21474836480` bytes;
`OOMPolicy=kill` was set. These limits apply to this service's cgroup, not the
whole host or a separately running Ollama service. The public unit template does
not contain these limits.

[BeliefStore](../../agent_core/world_model/belief_store.py) sets
`MAX_CURRENT_BELIEFS=2000`; [VectorStore](../../agent_core/semantic/vector_store.py)
sets `MAX_VECTORS=10000`. Both enforcement paths exist. Vector eviction uses
namespace priority and then age, rather than global age alone. These are bounds,
not current store contents. The [tick source](../../agent_core/homeostasis/core.py)
and [documentation linter](../../scripts/doc_lint.py) agree on **21 distinct
integer phase markers**; optional subphases and execution cadences differ.

The public revision has **226 reachable commits**, checked with `git rev-list
--count` and enumeration of `git log`. Curated snapshots and squash merges mean
this is not a measure of all development work, so it is not a headline result.

## Demo review

The existing MP4, GIF, poster and generated files were preserved. All **eight
entries** in the existing checksum manifest match. FFmpeg identifies a **76.73 s**
video at **1280×900, 30 fps**, with no audio stream listed; “77 seconds” is rounded.
Selected frames were inspected against the recording notes. The CSV parser finds
one header and **zero data rows**. The published provenance records one completed
job, two artifacts and no new job for the result follow-up. That is a recorded
single demonstration, not an independently repeated task-success experiment.

## Documentation checks

The repository documentation-drift linter and `git diff --check` pass. Markdown
lint reports zero issues for the six authored/reorganized entry documents
(line-length, table-alignment and acronym punctuation rules excluded). The four
historical reference documents introduce no additional lint findings compared
with their baseline; their pre-existing formatting issues remain.

All 144 Markdown link/image occurrences across those six entry documents were
checked: local paths and fragments resolve, and all nine distinct external URLs
returned HTTP 200. Remote media was checked by headers, not downloaded. Mermaid
was parsed and rendered in a local Chromium preview; the demo preview loaded and
the requested title plus nine section headings were present.

## Claims corrected or excluded

| Proposed / previous claim | Audit disposition |
|---|---|
| Around 7,262 passing tests | Historical. Replaced by the exact-revision CI result above; no extra passes inferred from collection. |
| Around 224 commits | Revision-dependent and not a work metric. Current audited public history has 226. |
| 1,365 knowledge entries; 4,194 traces | **unverified** as current counts. Historical tables lack a reproduced, contamination-checked current measurement. |
| 2,000 beliefs / 10,000 vectors as live totals | Recast as code-enforced retention bounds; occupancy was not measured. |
| 1.5 million JSONL rows / 1.1 GB / nine-hour outage | **unverified** as independently reconstructed measurements; excluded from portfolio result claims. |
| A 19-phase tick | Outdated count. Code has 21 numbered top-level phases plus subphases. |
| 10–12-hour hang | The source describes approximately 10.5 hours historically; used only with that attribution, not as a freshly measured duration. |
| DNS outage and repair | **unverified** incident chain in this audit; excluded. |
| Continuously running since February, same process | Unsupported uptime claim. Deployment history includes maintenance and restarts. |
| Self-repair autonomously fixes source code | Incorrect for this path: detection, gated task creation and operator acknowledgement. |
| Fully offline complete demo; one-command project execution | Incorrect. Local chat and separately configured project execution have different prerequisites. |
| Every Ollama call has a reliable HTTP timeout | Too broad: client-construction fallback can return the unbounded module API. |
| Old BeliefBuilder rebuild became seconds | No reproduced benchmark; retained the supported maintenance mechanism without the speed claim. |

## Documentation preservation and next evidence

Detailed runtime guidance and existing screenshots now live in the
[runtime guide](../runtime-guide.md). Architecture/model/persistence design
material and historical status documents remain, with dated notices and clearer
navigation. The [previous root README](https://github.com/erykaitools-beep/Maria/blob/47eaec0bed17ec18b431ea4eb769aa6b91676a9e/README.md)
remains available in Git history; its historical counters are not silently
promoted to current facts.

Useful next evidence is a reproducible endurance/failure-injection run,
a real-model quality/latency/memory evaluation with fixed dependencies,
publicly installable demo adapters, and physical voice/device acceptance.
The repeated sleep/examination interaction also merits a dedicated regression
test. These are follow-up items, not results of this documentation change.
