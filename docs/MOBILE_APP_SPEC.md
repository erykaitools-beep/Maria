# M.A.R.I.A. Mobile — Specification (MOBILE_APP_SPEC.md)

> **Status:** Stages 1–3 complete; Stage 4 (write actions) in progress. Screens run on live data (REST `Http*Repository` + `SocketChatRepository` chat); PWA installable.
> **Principle:** LOCAL until the app genuinely works (ADR-029 / publish-after-execution).
> **For the implementer (Codex/Claude):** this file is the contract. Read it fully before writing code; do not jump to Stage 2+ before Stage 1 is green.

---

## TL;DR (for Eryk — read this; the rest is for Codex)

- **What we're building:** not a chatbot — **an operator panel for Maria on the phone**. A window into the live system: conversation, state, projects, tasks, memory, autonomy.
- **The biggest thing we discovered:** **the backend already exists.** Maria's Web UI (Flask + SocketIO on the mini PC, `<MINI_PC_LAN_IP>:5000`) already has 100+ JSON endpoints + real-time chat + PIN login. **8 of the 9 screens can be powered by what ALREADY works.** We're not building a server from scratch. This cuts roughly half the roadmap from your original concept (the entire "Stage 3 — FastAPI/Supabase" is ~80% eliminated).
- **Construction analogy:** the utilities (power, water, sewage) are already in the building. We're building **a new apartment (the app) and connecting it to the existing risers** — we're not digging new foundations.
- **What this is NOT:** it's not "one task" — it's **a new project on a different stack** (Flutter/Dart). A separate repo, not inside `maria/`. But we go stage by stage, in order, the way you like.
- **How much work for you:** writing code = Codex/workflow, zero work on your part. **The only moment where you're needed:** build the APK and install it on the phone (once, with a single command or via the cloud) + test it live. I'll make that as painless as possible.
- **First building block (in order):** this spec → a mockup with fake data (does it look like Maria) → only then do we connect the live Maria.

---

## 1. Vision and non-goals

### What it is
M.A.R.I.A. Mobile = **a personal operating system for human–AI collaboration**:
```
AI Companion  +  Project Operating System  +  Autonomy Control Panel
```
Maria in your pocket as a command center: system, projects, memory, agents.

### Positioning (an important product decision)
The app **does NOT pretend that Maria is a person.** It presents her as **a cognitive-operational system managed by Eryk.**
- Instead of: "Hi, I'm your AI."
- Rather: `M.A.R.I.A. Core online. Last decision: awaiting approval. Active projects: 4. Risk: low.`

### Non-goals (what we're NOT doing initially — from the concept)
Payments, an app store, public accounts, an agent marketplace, social features, iOS right away, heavy animated graphics, full computer control, advanced autonomy. **Android + reuse of the existing backend + your real-world use.**

---

## 2. Architecture (the most important section — read carefully, Codex)

### Overriding rule
```
mobile app  ->  M.A.R.I.A. backend (existing maria_ui)  ->  models/memory/agents
```
**NEVER** `mobile app -> directly to OpenAI/Claude/NIM API.` No API keys in the app. The app talks ONLY to Maria's backend over the LAN.

### What already exists (REUSE) vs. what's new (BUILD)

| Layer | Status | Details |
|---|---|---|
| **Backend HTTP API** | ✅ EXISTS | `maria_ui/` Flask, 100+ JSON endpoints, bind `0.0.0.0:5000` |
| **Real-time chat** | ✅ EXISTS | SocketIO: `chat_message` (client→server) / `chat_response` (server→client) |
| **Auth** | ✅ EXISTS (to be extended) | PIN + Flask session cookie. **For mobile, add an API token** (see §7) |
| **Push notifications** | ✅ EXISTS (channel) | SocketIO `proactive_notification` (server→client) |
| **Mobile front-end** | 🔨 NEW | The entire Flutter app — this is 90% of the work |
| **Files endpoint** | 🔨 NEW (small) | `/api/files` upload/list — the only missing screen |
| **Chat mode (modes)** | 🔨 NEW (small) | `mode` param on `chat_message` → `master_prompt.py` variant (see §5) |

### Target diagram
```
+-------------------------+        LAN (HTTP + WebSocket)        +----------------------------+
|   M.A.R.I.A. Mobile     |  <-------------------------------->  |  maria_ui (Flask+SocketIO) |
|   (Flutter, Android)    |   REST /api/* + SocketIO chat        |  <MINI_PC_LAN_IP>:5000     |
|                         |   Auth: token + session              |                            |
|  Dashboard/Chat/Tasks   |                                      |  -> HomeostasisCore        |
|  Memory/System/Journal  |                                      |  -> OllamaBrain (chat)     |
|  Projects/Files/Settings|                                      |  -> Conductor / Goals      |
+-------------------------+                                      |  -> MemoryQuery / Bulletin |
                                                                 +----------------------------+
```

### Where the code lives
- **Separate repo:** `~/maria-mobile/` (NOT in the `maria/` repo — that's the Python brain, the app is a different stack).
- Small backend changes (API token, `/api/files`, `mode` param) go into the **existing `maria/` repo** (`maria_ui/`), done by Claude/Codex in a normal session.

---

## 3. Screens (9) — each mapped to REAL existing endpoints

Legend: ✅ READY (works on the existing API) · ⚠️ PARTIAL (exists, needs minor adaptation) · 🔨 NEW (a new endpoint is needed).

### 3.1 Dashboard (Start) — ✅ READY
The first screen = the dashboard, not an empty chat.
- Data: `GET /api/status/full` (mode, health_score, RAM/CPU/disk/uptime, goals counts, recent_events, alerts), `GET /api/learning/stats`, `GET /api/analysis/status`.
- View: greeting + Online/Offline status + active projects + pending tasks + risks/alerts + "next step".
- Quick actions: Chat / Add task / Check status / Continue project / Save observation.

### 3.2 Chat (Maria) — ✅ LIVE (2026-06-10, Stage 3 done)
- Send: SocketIO `chat_message {message}` (the real server has NO `mode` field — see §4). Receive: `chat_response {success, message, fallback, timeout?, maria_intent?, confabulation_flag?}` + `chat_status` statuses (learning_detected, possible_confabulation… → grey system lines in the conversation).
- History: `GET /api/chat/history` (last 50; timestamp = float epoch seconds). Clearing: `clear_history`.
- Server rate limit: **2 messages / 60 s** → the app shows "wait ~Xs". Timeout → a "busy" message (fallback=true). Protocol mapping: `lib/data/chat_wire.dart` (pure functions + contract tests).

### 3.3 Projects — ✅ LIVE (2026-06-10, Eryk's decision)
- **Resolved:** "Projects" = **conductor queues** (what Maria is working on): `GET /api/projects` (read-only) → per-project BuildStatus (phase, progress, blockers, counters) + recent tasks from `meta_data/*_task_queue.jsonl` (without descriptions — multi-kilobyte Codex briefs stay on the server).
- "What WE build" landed in a separate **Build** tab (drawer): `GET /api/build` = a build note (3 sections) + git log -30 (branch, ahead-of-origin, timeline).

### 3.4 Tasks — ✅ READY
- Two task types already exist:
  - **Agent tasks (Claude/Codex):** `GET /api/tasks`, `GET /api/tasks/<id>`, `POST /api/tasks {task_text, backend}`, `GET /api/tasks/<id>/pdf`.
  - **Learning goals:** `GET /api/learning/goals` (active/achieved/failed + progress).
- The statuses from the concept (To do / In progress / Awaiting decision / Error / Done…) map onto the lifecycle of tasks + goals.
- The multithreaded queue = a list with a status filter.

### 3.5 Memory — ✅ READY
- `GET /api/memory/query?topic=`, `GET /api/memory/gaps`, `GET /api/beliefs/recent`, `/api/beliefs/stats`, `/api/beliefs/gaps`.
- View: search by topic + "gaps" (low confidence) + recent beliefs with confidence + provenance.
- Memory editing (add / mark important / archive / delete) from the concept → **partly NEW** (a write API to memory is sensitive; read-only for Stage 1, write later behind a gate).

### 3.6 System — ✅ READY
- `GET /api/status` (quick: RAM%, CPU%, uptime, mode, health), `GET /api/status/full` (full: homeostasis mode ACTIVE/REDUCED/SLEEP/SURVIVAL, NIM budget, models, openclaw, planner).
- This is the screen that "ordinary AI apps don't have": Core/Memory/Local model/API model online-offline, last sync, autonomy level, risk.

### 3.7 Journal — ✅ READY
- `GET /api/traces` (decision traces: action_type, success, duration, k7_decision), `/api/traces/stats`, `/api/traces/failed`, `GET /api/analysis/latest` (K12 reports).
- This covers "logs as Decision/Change/Test/Restart/Task" from the concept (not raw log hell — structured entries).
- Eryk's experiments/reflections (manual journal entries) → a small NEW store, later.

### 3.8 Files — ✅ LIVE read + preview (2026-06-16)
- List: `GET /api/docs` (live). Preview: tapping a text file -> in-app
  `DocumentPreviewScreen` (`GET /api/docs/download/<file>` via `ApiClient.getText`,
  cap 200k chars, binary types -> "download via browser"). `d00c085`.
- ⏳ Remaining (write): `POST /api/files/upload`, `DELETE /api/files/<name>`, linking
  to a project. ~a small addition to `maria_ui/`. The upload FAB today = an honest "coming soon".

### 3.9 Settings — ✅ READY
- `GET/POST /api/user/profile` (name, response_style, autonomy_level, interests, facts, schedule), `POST /api/proactive/toggle`, `GET /api/capabilities`.
- Models/API/security/export/theme — some read-only from `/api/status/full`, the rest local to the UI.

### Coverage matrix (summary)
| Screen | Backend | Work |
|---|---|---|
| Dashboard | ✅ | front only |
| Chat | ✅ LIVE | done (Stage 3, 2026-06-10) |
| Projects | ✅ LIVE | done (conductor `/api/projects`, 2026-06-10) |
| Build | ✅ LIVE | done (new drawer tab, `/api/build`, 2026-06-10) |
| Tasks | ✅ | front only |
| Memory | ✅ (read) | front; write later |
| System | ✅ | front only |
| Journal | ✅ (read) | front; manual entries later |
| Files | ✅ LIVE (read+preview) | upload/delete (`/api/files`) later |
| Settings | ✅ | front only |

---

## 4. Chat modes (6) — CUT from the app (2026-06-10)

> **Verdict at Stage 3:** the mode switcher was REMOVED from the app when wiring
> up live chat. The real server accepts a bare `{message}` — the modes were
> guesswork from the mockup and would fake behavior that doesn't exist (principle:
> we fake nothing). If they are to return, it should be via the "clean path"
> below (real prompt variants in `master_prompt.py`), as a deliberate stage — not
> just UI.

Concept (kept for the future). Maria cannot be a single flat conversation. Modes:

| Mode (Polish UI) | key | Role |
|---|---|---|
| Maria | `normal` | everyday conversation, ideas, analysis |
| Architekt | `architect` | planning projects, code, structures, roadmaps |
| Audytor | `auditor` | no praise — errors, risks, weak points |
| Operator | `operator` | technical: server, logs, state, automation |
| Dziennik | `journal` | recording: reflections, experiments, observations |
| Szybko | `fast` | short, to the point, no philosophy |

### Implementation (honest)
- Backend today = a single `OllamaBrain.think(message)`, a single master prompt.
- **Clean path:** add a `mode` param to `chat_message`; the backend picks a prompt variant in `agent_core/llm/master_prompt.py` (SSoT). A small addition on the `maria/` side.
- **For Stage 1 (mockup):** modes = UI only (switcher + a different placeholder), no backend.

---

## 5. Tech stack

| Layer | Choice | Rationale |
|---|---|---|
| **App** | **Flutter** (Android-first) | one codebase for Android/iOS, good dashboards, Codex can handle it, dark operator UI |
| **State** | Riverpod (or Bloc) | clean layers, testable |
| **HTTP** | `dio` | interceptors (token/session), retry |
| **WebSocket** | `socket_io_client` | compatible with the Flask-SocketIO backend |
| **Local storage** | `hive` or `isar` | offline cache + mock data |
| **Backend** | **EXISTING `maria_ui` (Flask+SocketIO)** | we do NOT build FastAPI/Supabase from scratch |
| **Database** | none new initially | data from existing JSONL/endpoints; possibly later |

### Flutter code architecture (clean)
```
lib/
  core/        (theme, router, env, di)
  data/        (api clients: rest_client.dart, socket_client.dart; dto/; repositories/)
  domain/      (models: SystemStatus, Task, Goal, Belief, ChatMessage, Project, Trace; interfaces)
  features/
    dashboard/ chat/ projects/ tasks/ memory/ system/ journal/ files/ settings/
      (screen.dart, controller.dart, widgets/)
  mock/        (fake_data.dart — JSON matching the real shapes from §3)
```

---

## 6. Navigation and first screen

### Bottom bar (5 tabs, Polish UI labels)
```
Start | Maria | Projekty | Zadania | Pamiec
```
### Side menu (Polish UI labels)
```
System | Dziennik | Pliki | Ustawienia | Modele | Logi | Eksport | Bezpieczenstwo
```
### First screen = dashboard (example)
```
Good morning, Eryk.
M.A.R.I.A. status: Online
Active projects: 4
Pending tasks: 7
Last session: Mobile app
Risks: 2
Next step: prepare the specification for Codex
```

---

## 7. Security and auth

- **Today:** PIN → Flask session cookie (HttpOnly, SameSite=Lax). Chat rate limit 2 msgs/60s. Input sanitization.
- **For mobile (NEW, small):** add an **API token** (Bearer) to `maria_ui` — a mobile client doesn't cope well with a cookie session. Endpoint `POST /api/auth/token {pin} -> {token}`; token in the header + in the SocketIO handshake.
- **Iron rules:** no model keys in the app; the app talks to Maria over the LAN only; secrets never in the repo; the "Security" screen shows status only, not secrets.
- **External access (away from home):** not yet. LAN/VPN only. (Exposing it to the world = a separate decision, later, with a reverse proxy + TLS.)

---

## 8. Roadmap (staged — revised, because the backend exists)

> Your principle: "we go in order, no jumping around." Each stage ends with something you can **see and use.**

### Stage 0 — Spec & decisions (THIS file)
Eryk's approval + answers to §11. **Zero code.**

### Stage 1 — Mockup (fake data) ← the first real step for Codex
Flutter project + 9 screens + navigation + dark operator UI + **fake data matching the real JSON shapes** from §3. No backend.
**Result:** you click through the app on a phone/emulator and see "is this Maria, or just junk."

### Stage 2 — Connecting the live Maria (read-only)
API token for `maria_ui` (a small PR in `maria/`). Wire: Dashboard, System, Memory, Tasks, Journal → real endpoints over the LAN. Pull-to-refresh + polling.
**Result:** the app shows Maria's REAL state on your phone.

### Stage 3 — Live chat
SocketIO client → `chat_message`/`chat_response` + statuses + history.
**Result:** you talk with Maria from your phone.

### Stage 4 — Actions (write)  *(IN PROGRESS — 2026-06-16)*
`POST /api/tasks` (dispatch Claude/Codex), approve/reject experiments, profile editing, proactive toggle, action approve-gate.
**Result:** you control Maria from your phone.
- ✅ **Inbox** approve/reject (`POST /api/approval/act`, layer 2) — the first write.
- ✅ **Task dispatch** (`POST /api/tasks`) — the "+" form fires a real Claude/Codex (busy/error inline, optimistic PENDING row). `34e5c68`.
- ✅ **Profile editing** (`POST /api/user/profile`) — Save persists name/style/autonomy + an interests diff. `34e5c68`.
- ✅ **Proactive toggle** (`GET /api/proactive/status` + `POST /api/proactive/toggle`) — the switch hydrates from live state and works immediately (optimistic, reverts on error). `34e5c68`.
- ⏳ **Remaining:** approve/reject experiments (`/api/experiments/*` — backend ready, no screen in the app), profile: adding facts/schedule, Telegram alerts (no toggle endpoint — read-only info row today).

### Stage 5 — Modes + missing endpoints
`mode` param + `master_prompt.py` variants; `/api/files`; `/api/projects` (if decided); search.
**Result:** the full 9 screens + 6 modes.

### Stage 6 — Autonomy/alerts + polish
Push: `proactive_notification` → native notifications (FCM/local). Schedules, export (JSON/MD/PDF), theme, final polish.
**Result:** a command center with alerts.

---

## 9. First task for Codex (Stage 1 — copy-paste)

```
You are building M.A.R.I.A. Mobile, a Flutter Android-first app that acts as an
operator dashboard for a personal AI system (NOT a generic chatbot).

SCOPE OF THIS TASK (Stage 1 only): a navigable prototype with realistic FAKE data.
Do NOT connect any real API, backend, model, or auth yet.

Build:
1. A new Flutter project with clean architecture (core / data / domain / features / mock).
2. Bottom navigation: Start | Maria | Projekty | Zadania | Pamiec  (Polish UI labels).
   Side drawer: System | Dziennik | Pliki | Ustawienia.
3. Nine screens, dark minimalist "operator control room" theme (mostly black/grey,
   one accent color, high readability, zero playful graphics):
   Dashboard, Chat (with a mode switcher: Maria/Architekt/Audytor/Operator/Dziennik/Szybko),
   Projects, Tasks (queue with status chips), Memory (topic search + belief cards),
   System (status cards: Core/Memory/Local model/API model online-offline, RAM/CPU/uptime),
   Journal (decision-trace list), Files (list + upload placeholder), Settings (profile form).
4. Realistic mock data in lib/mock/ whose JSON shapes MATCH the real backend
   (e.g. SystemStatus has mode/health_score/ram/cpu/uptime; Task has task_id/status/backend;
   Goal has progress; Belief has confidence; ChatMessage has role/content/timestamp).
5. Riverpod for state, go_router for routing, dio + socket_io_client as deps (unused yet),
   hive for local cache. Repositories return mock data behind an interface so Stage 2 can
   swap to real HTTP without touching the UI.

Deliverable: a clickable app that runs on an Android emulator and LOOKS like Maria's
operator panel. Include a README with `flutter run` instructions and a screenshot checklist.
Conventions: English code + docstrings, no emoji in code, type-safe models, widget tests
for navigation.
```

---

## 10. What Eryk must do (honest — minimal, but not zero)

1. **Approve this spec** + answer §11 (5 min).
2. **Build the APK and install it on the phone** — the only step that Codex/workflow can't do for you remotely. Options (we'll pick the easiest):
   - (a) Flutter SDK on the mini PC / your computer → `flutter build apk` → you install the file on the phone. I'll write a script; you click once.
   - (b) Cloud build (Codemagic / GitHub Actions) → you get a ready APK via a link. Zero local Flutter installation.
3. **Test it live** and say "this looks like Maria / this is junk" — the rest is iteration.

The backend additions (API token, `/api/files`, `mode`) are done by Claude/Codex in the `maria/` repo in a normal session — zero work on your part beyond review.

---

## 11. Open decisions (needed from Eryk)

1. **"Projects" — what exactly?** Your product projects (M.A.R.I.A., AI Mirror, X/Twitter, Finance…) are a new store. For Stage 1, do we build them as a fake list and settle the real model in Stage 5? (recommendation: YES)
2. **Where we build the APK** — (a) Flutter locally or (b) cloud/CI? (recommendation: start with (a) on the mini PC; if it hurts → (b))
3. **Who writes Stage 1** — Codex solo (one big prompt from §9) or a multi-agent workflow (in parallel: skeleton + theme + 9 screens + mock + tests, then assembly)? (recommendation: workflow — faster and more consistent for 9 screens at once)
4. **Working repo name:** `maria-mobile`? (recommendation: YES, private)
5. **Accent color** for the operator UI: purple / blue / green? (recommendation: pick one — it affects the whole theme)

---

## 12. Visual standard (design system) — "standard first"

> Rule: **no new screen/component hardcodes values.** Everything comes from the tokens + helpers below. Audit 2026-06-09: colors and components are already disciplined (0 color hardcodes in screens). The only gap: **typography** (12 sizes in use → the 8-step scale below).

### 12.1 Colors (tokens — `lib/core/theme/app_colors.dart`, do NOT change ad-hoc)
| Role | Token | Hex |
|---|---|---|
| Background | `background` | `#0B0B0F` |
| Panel | `surface` / `surfaceAlt` | `#16161D` / `#1E1E27` |
| Border | `border` | `#2A2A35` |
| Text | `textPrimary` / `textMuted` | `#E5E5EA` / `#8A8A94` |
| **Brand** | `accent` / `accentDeep` | `#8B5CF6` / `#7C3AED` |
| State: online | `online` | `#34D399` |
| State: warn | `warn` | `#FBBF24` |
| State: offline | `offline` | `#F87171` |

**Color rule (iron):** purple = **brand** (action, navigation, accent — buttons, autonomy, spinner). Green/amber/red = **state/health ONLY** (signaling). Never purple as a status; never green as decoration. That's why the System screen "isn't purple" — its banner is health signaling (by design).

### 12.2 Typography (8-step scale — TO BE INTRODUCED) — `lib/core/theme/app_type.dart`
Today 12 ad-hoc sizes (10–26). Standard = 8 named steps; migrate screens to them:
| Token | px / weight | Use |
|---|---|---|
| `display` | 26 / 800 | large numbers (health, hero metrics) |
| `title` | 20 / 700 | screen title |
| `heading` | 18 / 700 | card/banner heading |
| `subtitle` | 15 / 600 | organ label, important value |
| `body` | 14 / 500 | standard text |
| `label` | 13 / 500 | status rows, descriptions |
| `caption` | 12 / 600 | pills, captions |
| `micro` | 11 / 600 | navigation, micro-captions |
Font: Roboto. Numbers/metrics: `FontFeature.tabularFigures()` (even digits).

### 12.3 Rhythm and shape
- **Spacing (step 4):** 4 / 8 / 12 / 16 / 22 / 28. Card padding = 16. Gap between cards = 12. Section↔section = 18–22.
- **Radius:** `AppTheme.radius` = 14 (cards, panels). Pills = 999.
- **Card:** `surface` + 1px `border` + radius 14. Only via `AppTheme.cardDecoration()` or the `Card` theme — not by hand.

### 12.4 Components (SSoT helpers — use, don't clone)
`AppTheme.cardDecoration()` · `AppTheme.statusPill(label, kind)` · `AppTheme.statusColor(kind)` · `AppTheme.boolStatus(bool)`. Pill = color background @14% + border @50% + dot. Section header = UPPERCASE, `caption`, letterSpacing 1.2, `textMuted`.

### 12.5 Screen states (every data screen MUST have 3)
1. **loading** — spinner in `accent` + short `textMuted` text (not a blank screen).
2. **error** — `cloud_off` icon in `offline` + reason + a "Try again" button.
3. **empty** — icon + a one-sentence prompt (not an empty list).
Plus **pull-to-refresh** on every data screen.

### 12.6 Overriding principle
"**Operator control room**": dark, information-dense, readable, **data > decoration**. Zero decorative animations (non-goal §1) — only micro state transitions. This is not an MVP — the finish must be even across all 9 screens.

---

## 13. Backlog / extras (PARKING — later, not now)

> Everything new lands HERE, not in code, until the standard (§12) is fully applied to what we already have. Order = to be settled with Eryk.

**Extra ideas (extras):**
- **Tab coloring** *(Eryk's idea, 2026-06-09)* — the "System" icon in the bottom bar tinted by health state (green/amber/red) → Maria's condition visible without opening the screen.
- Skeleton loaders instead of spinners; light haptics on actions.

**Data completion (read-only):**
- ~~**Dashboard Stage 2b**~~ ✅ 2026-06-10 — "active projects" from the conductor (`/api/projects`) + "next step" from the build note (`/api/build`); a "next step from the strategist" variant is possible later, would require a new endpoint.
- **Live tiles:** Memory (`/api/memory/query`, `/api/beliefs/recent`), Tasks (`/api/tasks`, `/api/learning/goals`), Journal (`/api/traces`), Settings (`/api/user/profile`).

**Larger stages (from §8):**
- ~~Live chat (Stage 3)~~ ✅ 2026-06-10 · ~~`/api/projects`~~ ✅ 2026-06-10 (conductor) + Build tab (`/api/build`) · **Actions/write (Stage 4) — IN PROGRESS 2026-06-16: task-create + profile-save + proactive-toggle ✅; experiments approve/reject remaining** · Chat modes as real server personas (§4, if they return) + `/api/files` write (Stage 5).
- **Access beyond WiFi:** Tailscale (private tunnel) + API token in `maria_ui` + native APK via the cloud (the mini PC has no Android SDK). (Stage 6 / remote access.)
- Push: `proactive_notification` → native notifications (FCM/local).

---

*A living document. Update at every completed stage. SSoT for the M.A.R.I.A. Mobile project.*
