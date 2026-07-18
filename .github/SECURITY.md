# Security Policy

## Reporting a vulnerability

**Please do not open a public issue for security problems.**

Instead, use one of these private channels:

- GitHub's **[Report a vulnerability](https://github.com/erykaitools-beep/Maria/security/advisories/new)** flow (preferred), or
- Contact the maintainer through their GitHub profile.

Please include:

- a description of the issue and its impact,
- steps to reproduce (or a proof of concept),
- the affected component and, if known, the commit.

We aim to acknowledge a report within **72 hours** and to share a fix or
mitigation timeline after triage.

## Scope

M.A.R.I.A. is offline-first and runs locally on hardware you control. The most
security-relevant areas are:

- the Flask Web UI (PIN-protected) and its network binding (`MARIA_HOST` / `MARIA_PORT`);
- secret handling — `.env` holds the PIN and any optional tokens and is never committed;
- optional integrations that take credentials (Telegram bot token, NVIDIA NIM key).

Out of scope: attacks that assume an already-compromised host, and the intended
behavior of a self-hosted agent acting on your own machine.

## Supported versions

This is a single-branch project; security fixes land on `main`.
