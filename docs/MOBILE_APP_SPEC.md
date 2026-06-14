# M.A.R.I.A. Mobile — Specyfikacja (MOBILE_APP_SPEC.md)

> **Status:** Etap 2 W TOKU — **System + Dashboard na ŻYWYCH danych** (`/api/status/full`, commit `f977458` w `~/maria-mobile`). Live web preview na telefonie: http://<MINI_PC_LAN_IP>:5000/static/mobile/index.html . **Aktualny fokus (2026-06-09): standard-first** — dociągamy co mamy do jednego standardu wizualnego (§12), nowe funkcje parkujemy w backlogu (§13). Decyzja Eryka: „najpierw standard, później rozszerzenie o dodatki — inaczej będziemy dodawać i dodawać a będzie źle wyglądać". Handoff: `claude_notes/2026-06-08_mobile_app_etap1.md`.
> **Zasada:** LOKALNE do czasu aż aplikacja realnie działa (ADR-029 / publish-after-execution). Nie pushować publicznie.
> **Dla Codexa/Claude:** ten plik jest kontraktem. Czytaj cały przed pisaniem kodu. Nie skacz do Etapu 2+ bez zielonego Etapu 1.

---

## TL;DR (dla Eryka — przeczytaj to, reszta jest dla Codexa)

- **Co budujemy:** nie chatbota — **panel operatorski Marii na telefon**. Okno na żywy system: rozmowa, stan, projekty, zadania, pamięć, autonomia.
- **Największa rzecz, którą odkryliśmy:** **backend już istnieje.** Web UI Marii (Flask + SocketIO na mini PC, `<MINI_PC_LAN_IP>:5000`) ma już 100+ endpointów JSON + czat real-time + logowanie PIN. **8 z 9 ekranów da się zasilić tym, co JUŻ działa.** Nie budujemy serwera od zera. To ucina jakieś pół roadmapy z Twojej koncepcji (cały „Etap 3 — FastAPI/Supabase" w 80% odpada).
- **Analogia budowlana:** instalacja (prąd, woda, kanalizacja) jest już w budynku. Budujemy **nowe mieszkanie (apkę) i podłączamy do istniejących pionów** — nie kopiemy fundamentów od nowa.
- **Co to NIE jest:** to nie „jedno zadanie" — to **nowy projekt na innym stacku** (Flutter/Dart). Osobne repo, nie w `maria/`. Ale idziemy etapami, po kolei, jak lubisz.
- **Ile Twojej roboty:** pisanie kodu = Codex/workflow, zero Twojej roboty. **Jedyny moment, gdzie musisz Ty:** zbudować APK i wgrać na telefon (raz, jednym poleceniem albo przez chmurę) + testować na żywo. To napiszę jak najmniej-boleśnie.
- **Pierwszy klocek (po kolei):** ten spec → makieta z fałszywymi danymi (czy wygląda jak Maria) → dopiero potem podłączamy żywą Marię.

---

## 1. Wizja i non-goals

### Czym jest
M.A.R.I.A. Mobile = **osobisty system operacyjny do współpracy człowiek–AI**:
```
AI Companion  +  Project Operating System  +  Autonomy Control Panel
```
Maria w telefonie jako centrum dowodzenia: system, projekty, pamięć, agenci.

### Pozycjonowanie (ważna decyzja produktowa)
Aplikacja **NIE udaje, że Maria jest osobą.** Pokazuje ją jako **system poznawczo-operacyjny zarządzany przez Eryka.**
- Zamiast: „Hej, jestem twoją AI."
- Raczej: `M.A.R.I.A. Core online. Ostatnia decyzja: oczekuje na zatwierdzenie. Aktywne projekty: 4. Ryzyko: niskie.`

### Non-goals (czego NIE robimy na start — z koncepcji)
Płatności, sklep, publiczne konta, marketplace agentów, funkcje social, iOS od razu, ciężka animowana grafika, pełne sterowanie komputerem, zaawansowana autonomia. **Android + reużycie istniejącego backendu + Twoje realne użycie.**

---

## 2. Architektura (najważniejsza sekcja — czytaj uważnie, Codex)

### Reguła nadrzędna
```
mobile app  ->  backend M.A.R.I.A. (istniejący maria_ui)  ->  modele/pamięć/agenci
```
**NIGDY** `mobile app -> bezpośrednio OpenAI/Claude/NIM API.` Żadnych kluczy API w aplikacji. Aplikacja gada TYLKO z backendem Marii po LAN.

### Co już istnieje (REUSE) vs co jest nowe (BUILD)

| Warstwa | Stan | Szczegóły |
|---|---|---|
| **Backend HTTP API** | ✅ ISTNIEJE | `maria_ui/` Flask, 100+ endpointów JSON, bind `0.0.0.0:5000` |
| **Czat real-time** | ✅ ISTNIEJE | SocketIO: `chat_message` (client→server) / `chat_response` (server→client) |
| **Auth** | ✅ ISTNIEJE (do rozszerzenia) | PIN + Flask session cookie. **Dla mobile dodać token API** (patrz §7) |
| **Powiadomienia push** | ✅ ISTNIEJE (kanał) | SocketIO `proactive_notification` (server→client) |
| **Front-end mobilny** | 🔨 NOWE | Cała apka Flutter — to jest 90% pracy |
| **Endpoint plików** | 🔨 NOWE (mały) | `/api/files` upload/list — jedyny brakujący ekran |
| **Tryb czatu (modes)** | 🔨 NOWE (mały) | Param `mode` do `chat_message` → wariant `master_prompt.py` (patrz §5) |

### Diagram docelowy
```
+-------------------------+        LAN (HTTP + WebSocket)        +----------------------------+
|   M.A.R.I.A. Mobile     |  <-------------------------------->  |  maria_ui (Flask+SocketIO) |
|   (Flutter, Android)    |   REST /api/* + SocketIO chat        |  <MINI_PC_LAN_IP>:5000       |
|                         |   Auth: token + session              |                            |
|  Dashboard/Chat/Tasks   |                                      |  -> HomeostasisCore        |
|  Memory/System/Journal  |                                      |  -> OllamaBrain (chat)     |
|  Projects/Files/Settings|                                      |  -> Conductor / Goals      |
+-------------------------+                                      |  -> MemoryQuery / Bulletin |
                                                                 +----------------------------+
```

### Gdzie żyje kod
- **Osobne repo:** `~/maria-mobile/` (NIE w repo `maria/` — to mózg w Pythonie, apka to inny stack).
- Małe zmiany w backendzie (token API, `/api/files`, `mode` param) idą do **istniejącego repo `maria/`** (`maria_ui/`), robi je Claude/Codex w normalnej sesji.

---

## 3. Ekrany (9) — każdy zmapowany na REALNE istniejące endpointy

Legenda: ✅ READY (działa na istniejącym API) · ⚠️ PARTIAL (jest, wymaga drobnego dopasowania) · 🔨 NEW (potrzebny nowy endpoint).

### 3.1 Dashboard (Start) — ✅ READY
Pierwszy ekran = dashboard, nie pusty czat.
- Dane: `GET /api/status/full` (mode, health_score, RAM/CPU/disk/uptime, goals counts, recent_events, alerts), `GET /api/learning/stats`, `GET /api/analysis/status`.
- Widok: powitanie + status Online/Offline + aktywne projekty + zadania oczekujące + ryzyka/alerty + „następny krok".
- Szybkie przyciski: Porozmawiaj / Dodaj zadanie / Sprawdź stan / Kontynuuj projekt / Zapisz obserwację.

### 3.2 Chat (Maria) — ✅ LIVE (2026-06-10, Etap 3 done)
- Wysyłka: SocketIO `chat_message {message}` (realny serwer NIE ma pola `mode` — patrz §4). Odbiór: `chat_response {success, message, fallback, timeout?, maria_intent?, confabulation_flag?}` + statusy `chat_status` (learning_detected, possible_confabulation… → szare linie systemowe w rozmowie).
- Historia: `GET /api/chat/history` (ostatnie 50; timestamp = float epoch-sekundy). Czyszczenie: `clear_history`.
- Rate limit serwera: **2 wiadomości / 60 s** → apka pokazuje „poczekaj ~Xs". Timeout → komunikat „zajęta" (fallback=true). Mapowanie protokołu: `lib/data/chat_wire.dart` (czyste funkcje + testy kontraktu).

### 3.3 Projekty — ✅ LIVE (2026-06-10, decyzja Eryka)
- **Rozstrzygnięte:** „Projekty" = **kolejki konduktora** (nad czym pracuje Maria): `GET /api/projects` (read-only) → per projekt BuildStatus (faza, postęp, blokery, liczniki) + ostatnie zadania z `meta_data/*_task_queue.jsonl` (bez opisów — wielokilobajtowe briefy Codexa zostają na serwerze).
- „Co budujemy MY" wylądowało w osobnej zakładce **Budowa** (szuflada): `GET /api/build` = notka `docs/BUILD_NOW.md` (3 sekcje PL, aktualizowana na koniec sesji Claude) + git log -30 (branch, ahead-of-origin, oś czasu).

### 3.4 Zadania (Tasks) — ✅ READY
- Dwa typy zadań już są:
  - **Agent tasks (Claude/Codex):** `GET /api/tasks`, `GET /api/tasks/<id>`, `POST /api/tasks {task_text, backend}`, `GET /api/tasks/<id>/pdf`.
  - **Learning goals:** `GET /api/learning/goals` (active/achieved/failed + progress).
- Statusy z koncepcji (Do zrobienia / W trakcie / Czeka na decyzję / Błąd / Zakończone…) mapują się na lifecycle tasków + goali.
- Kolejka wielowątkowa = lista z filtrem statusu.

### 3.5 Pamięć (Memory) — ✅ READY
- `GET /api/memory/query?topic=`, `GET /api/memory/gaps`, `GET /api/beliefs/recent`, `/api/beliefs/stats`, `/api/beliefs/gaps`.
- Widok: szukaj po temacie + „luki" (niska pewność) + ostatnie beliefy z confidence + provenance.
- Edycja pamięci (dodaj/oznacz ważne/archiwizuj/usuń) z koncepcji → **częściowo NEW** (write-API do pamięci to wrażliwa rzecz; na Etap 1 read-only, write później za bramką).

### 3.6 System (Stan) — ✅ READY
- `GET /api/status` (szybki: RAM%, CPU%, uptime, mode, health), `GET /api/status/full` (pełny: homeostasis mode ACTIVE/REDUCED/SLEEP/SURVIVAL, NIM budget, modele, openclaw, planner).
- To jest ten ekran, którego „zwykłe apki AI nie mają": Core/Memory/Local model/API model online-offline, last sync, autonomy level, risk.

### 3.7 Dziennik (Journal) — ✅ READY
- `GET /api/traces` (decision traces: action_type, success, duration, k7_decision), `/api/traces/stats`, `/api/traces/failed`, `GET /api/analysis/latest` (raporty K12).
- To pokrywa „logi jako Decyzja/Zmiana/Test/Restart/Zadanie" z koncepcji (nie surowe piekło logów — strukturalne wpisy).
- Eksperymenty/refleksje Eryka (ręczne wpisy dziennika) → mały NEW store, później.

### 3.8 Pliki (Files) — 🔨 NEW (jedyny ekran bez backendu)
- Istnieje tylko `GET /api/docs` + `/api/docs/download/<file>` (read).
- Potrzebne: `GET /api/files` (list), `POST /api/files/upload`, `DELETE /api/files/<name>`, powiązanie z projektem. ~mały dodatek do `maria_ui/`.

### 3.9 Ustawienia (Settings) — ✅ READY
- `GET/POST /api/user/profile` (name, response_style, autonomy_level, interests, facts, schedule), `POST /api/proactive/toggle`, `GET /api/capabilities`.
- Modele/API/bezpieczeństwo/eksport/motyw — część read-only z `/api/status/full`, reszta UI-lokalnie.

### Macierz pokrycia (skrót)
| Ekran | Backend | Praca |
|---|---|---|
| Dashboard | ✅ | front only |
| Chat | ✅ LIVE | done (Etap 3, 2026-06-10) |
| Projekty | ✅ LIVE | done (konduktor `/api/projects`, 2026-06-10) |
| Budowa | ✅ LIVE | done (nowa zakładka w szufladzie, `/api/build`, 2026-06-10) |
| Zadania | ✅ | front only |
| Pamięć | ✅ (read) | front; write później |
| System | ✅ | front only |
| Dziennik | ✅ (read) | front; ręczne wpisy później |
| Pliki | 🔨 | front + nowy `/api/files` |
| Ustawienia | ✅ | front only |

---

## 4. Tryby czatu (6) — WYCIĘTE z apki (2026-06-10)

> **Werdykt przy Etapie 3:** przełącznik trybów USUNIĘTY z apki przy podpinaniu
> żywego czatu. Realny serwer przyjmuje gołe `{message}` — tryby były
> zgadywanką z makiety i udawałyby zachowanie, którego nie ma (zasada: nic
> nie udajemy). Jeśli mają wrócić, to „czystą drogą" poniżej (prawdziwe
> warianty promptu w `master_prompt.py`), jako świadomy etap — nie sam UI.

Koncepcja (zachowana na przyszłość). Maria nie może być jedną płaską rozmową. Tryby:

| Tryb (UI PL) | key | Rola |
|---|---|---|
| Maria | `normal` | codzienna rozmowa, pomysły, analiza |
| Architekt | `architect` | planowanie projektów, kodu, struktur, roadmap |
| Audytor | `auditor` | bez chwalenia — błędy, ryzyka, słabe punkty |
| Operator | `operator` | technicznie: serwer, logi, stan, automatyzacja |
| Dziennik | `journal` | zapis: refleksje, eksperymenty, obserwacje |
| Szybko | `fast` | krótko, konkret, bez filozofii |

### Implementacja (honest)
- Backend dziś = jeden `OllamaBrain.think(message)`, jeden master prompt.
- **Czysta droga:** dodać param `mode` do `chat_message`; backend wybiera wariant promptu w `agent_core/llm/master_prompt.py` (SSoT). Mały dodatek po stronie `maria/`.
- **Na Etap 1 (makieta):** tryby = tylko UI (przełącznik + inny placeholder), bez backendu.

---

## 5. Stack techniczny

| Warstwa | Wybór | Uzasadnienie |
|---|---|---|
| **App** | **Flutter** (Android-first) | jeden kod Android/iOS, dobre dashboardy, Codex ogarnie, ciemny operator-UI |
| **State** | Riverpod (lub Bloc) | czyste warstwy, testowalne |
| **HTTP** | `dio` | interceptory (token/session), retry |
| **WebSocket** | `socket_io_client` | kompatybilny z Flask-SocketIO backendu |
| **Local storage** | `hive` lub `isar` | offline cache + makieta danych |
| **Backend** | **ISTNIEJĄCY `maria_ui` (Flask+SocketIO)** | NIE budujemy FastAPI/Supabase od zera |
| **Baza** | brak nowej na start | dane z istniejących JSONL/endpointów; ew. później |

### Architektura kodu Flutter (clean)
```
lib/
  core/        (theme, router, env, di)
  data/        (api clients: rest_client.dart, socket_client.dart; dto/; repositories/)
  domain/      (models: SystemStatus, Task, Goal, Belief, ChatMessage, Project, Trace; interfaces)
  features/
    dashboard/ chat/ projects/ tasks/ memory/ system/ journal/ files/ settings/
      (screen.dart, controller.dart, widgets/)
  mock/        (fake_data.dart — JSON dopasowane do realnych kształtów z §3)
```

---

## 6. Nawigacja i pierwszy ekran

### Dolny pasek (5 zakładek)
```
Start | Maria | Projekty | Zadania | Pamięć
```
### Menu boczne
```
System | Dziennik | Pliki | Ustawienia | Modele | Logi | Eksport | Bezpieczeństwo
```
### Pierwszy ekran = dashboard (przykład)
```
Dzień dobry, Eryk.
M.A.R.I.A. status: Online
Aktywne projekty: 4
Zadania oczekujące: 7
Ostatnia sesja: Aplikacja mobilna
Ryzyka: 2
Następny krok: przygotować specyfikację dla Codex
```

---

## 7. Bezpieczeństwo i auth

- **Dziś:** PIN → Flask session cookie (HttpOnly, SameSite=Lax). Rate-limit czatu 2 wiad./60s. Sanityzacja inputu.
- **Dla mobile (NEW, mały):** dodać **token API** (Bearer) do `maria_ui` — mobilny klient nie żyje dobrze na cookie-session. Endpoint `POST /api/auth/token {pin} -> {token}`; token w nagłówku + w handshake SocketIO.
- **Reguły żelazne:** żadnych kluczy modeli w apce; apka tylko po LAN do Marii; sekrety nigdy w repo; ekran „Bezpieczeństwo" pokazuje tylko status, nie sekrety.
- **Dostęp z zewnątrz (poza domem):** na razie NIE. Tylko LAN/VPN. (Wystawianie na świat = osobna decyzja, później, z reverse-proxy + TLS.)

---

## 8. Roadmapa (etapami — zrewidowana, bo backend istnieje)

> Twoja zasada: „idziemy po kolei, nie ma co skakać." Każdy etap kończy się czymś, co **widać i działa.**

### Etap 0 — Spec & decyzje (TEN plik)
Akceptacja Eryka + odpowiedzi na §11. **Zero kodu.**

### Etap 1 — Makieta (fake data) ← pierwszy realny krok dla Codexa
Flutter project + 9 ekranów + nawigacja + ciemny operator-UI + **fałszywe dane dopasowane do realnych kształtów JSON** z §3. Bez backendu.
**Wynik:** klikasz apkę na telefonie/emulatorze, widzisz „czy to jest Maria, czy zwykły śmieć."

### Etap 2 — Podłączenie żywej Marii (read-only)
Token API do `maria_ui` (mały PR w `maria/`). Wire: Dashboard, System, Pamięć, Zadania, Dziennik → realne endpointy po LAN. Pull-to-refresh + polling.
**Wynik:** apka pokazuje PRAWDZIWY stan Marii na Twoim telefonie.

### Etap 3 — Chat na żywo
SocketIO client → `chat_message`/`chat_response` + statusy + historia.
**Wynik:** rozmawiasz z Marią z telefonu.

### Etap 4 — Akcje (write)
`POST /api/tasks` (zlecaj Claude/Codex), approve/reject eksperymentów, edycja profilu, proactive toggle, approve-gate akcji.
**Wynik:** sterujesz Marią z telefonu.

### Etap 5 — Tryby + brakujące endpointy
`mode` param + warianty `master_prompt.py`; `/api/files`; `/api/projects` (jeśli zdecydowane); search.
**Wynik:** pełne 9 ekranów + 6 trybów.

### Etap 6 — Autonomia/alerty + polish
Push: `proactive_notification` → natywne powiadomienia (FCM/local). Harmonogramy, eksport (JSON/MD/PDF), motyw, dopieszczenie.
**Wynik:** centrum dowodzenia z alertami.

---

## 9. Pierwsze zadanie dla Codexa (Etap 1 — kopiuj-wklej)

```
You are building M.A.R.I.A. Mobile, a Flutter Android-first app that acts as an
operator dashboard for a personal AI system (NOT a generic chatbot).

SCOPE OF THIS TASK (Etap 1 only): a navigable prototype with realistic FAKE data.
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
   hive for local cache. Repositories return mock data behind an interface so Etap 2 can
   swap to real HTTP without touching the UI.

Deliverable: a clickable app that runs on an Android emulator and LOOKS like Maria's
operator panel. Include a README with `flutter run` instructions and a screenshot checklist.
Conventions: English code + docstrings, no emoji in code, type-safe models, widget tests
for navigation.
```

---

## 10. Co musi zrobić Eryk (honest — minimum, ale nie zero)

1. **Zaakceptować ten spec** + odpowiedzieć na §11 (5 min).
2. **Zbudować APK i wgrać na telefon** — to jedyny krok, którego Codex/workflow nie zrobią za Ciebie zdalnie. Opcje (wybierzemy najłatwiejszą):
   - (a) Flutter SDK na mini PC / Twoim kompie → `flutter build apk` → wgrasz plik na telefon. Napiszę skrypt, klikasz raz.
   - (b) Chmurowy build (Codemagic / GitHub Actions) → dostajesz gotowy APK linkiem. Zero lokalnej instalacji Fluttera.
3. **Testować na żywo** i mówić „to wygląda jak Maria / to śmieć" — reszta to iteracja.

Backend-owe dodatki (token API, `/api/files`, `mode`) robi Claude/Codex w repo `maria/` w normalnej sesji — Twojej roboty zero poza review.

---

## 11. Otwarte decyzje (potrzebuję od Eryka)

1. **„Projekty" — co to dokładnie?** Twoje projekty produktowe (M.A.R.I.A., AI Mirror, X/Twitter, Finanse…) to nowy store. Czy na Etap 1 robimy je jako fake-listę, a realny model ustalamy w Etapie 5? (rekomendacja: TAK)
2. **Gdzie budujemy APK** — (a) Flutter lokalnie czy (b) chmura/CI? (rekomendacja: zacznij od (a) na mini PC, jak boli → (b))
3. **Kto pisze Etap 1** — Codex solo (jeden duży prompt z §9) czy workflow wieloagentowy (równolegle: szkielet + theme + 9 ekranów + mock + testy, potem złożenie)? (rekomendacja: workflow — szybciej i spójniej dla 9 ekranów naraz)
4. **Nazwa robocza repo:** `maria-mobile`? (rekomendacja: TAK, prywatne)
5. **Kolor akcentu** operator-UI: fiolet / niebieski / zielony? (rekomendacja: jeden, zdecyduj — wpływa na cały theme)

---

## 12. Standard wizualny (design system) — „najpierw standard"

> Reguła: **żaden nowy ekran/komponent nie hardcoduje wartości.** Wszystko z tokenów + helperów poniżej. Audyt 2026-06-09: kolory i komponenty już zdyscyplinowane (0 hardcodów koloru w ekranach). Jedyna luka: **typografia** (12 rozmiarów w użyciu → skala 8 stopni poniżej).

### 12.1 Kolory (tokeny — `lib/core/theme/app_colors.dart`, NIE zmieniać ad-hoc)
| Rola | Token | Hex |
|---|---|---|
| Tło | `background` | `#0B0B0F` |
| Panel | `surface` / `surfaceAlt` | `#16161D` / `#1E1E27` |
| Obwódka | `border` | `#2A2A35` |
| Tekst | `textPrimary` / `textMuted` | `#E5E5EA` / `#8A8A94` |
| **Marka** | `accent` / `accentDeep` | `#8B5CF6` / `#7C3AED` |
| Stan: online | `online` | `#34D399` |
| Stan: warn | `warn` | `#FBBF24` |
| Stan: offline | `offline` | `#F87171` |

**Reguła koloru (żelazna):** fiolet = **marka** (akcja, nawigacja, akcent — przyciski, autonomia, spinner). Zielony/bursztyn/czerwony = **WYŁĄCZNIE stan/zdrowie** (sygnalizacja). Nigdy fiolet jako status; nigdy zielony jako dekoracja. Dlatego ekran System „nie jest fioletowy" — jego baner to sygnalizacja kondycji (by design).

### 12.2 Typografia (skala 8 stopni — DO WPROWADZENIA) — `lib/core/theme/app_type.dart`
Dziś 12 ad-hoc rozmiarów (10–26). Standard = 8 nazwanych stopni; migrować ekrany do nich:
| Token | px / waga | Użycie |
|---|---|---|
| `display` | 26 / 800 | duże liczby (health, metryki hero) |
| `title` | 20 / 700 | tytuł ekranu |
| `heading` | 18 / 700 | nagłówek karty/banera |
| `subtitle` | 15 / 600 | etykieta organu, ważna wartość |
| `body` | 14 / 500 | tekst standardowy |
| `label` | 13 / 500 | wiersze stanu, opisy |
| `caption` | 12 / 600 | pille, podpisy |
| `micro` | 11 / 600 | nawigacja, mikro-podpisy |
Font: Roboto. Liczby/metryki: `FontFeature.tabularFigures()` (równe cyfry).

### 12.3 Rytm i kształt
- **Spacing (krok 4):** 4 / 8 / 12 / 16 / 22 / 28. Padding karty = 16. Odstęp między kartami = 12. Sekcja↔sekcja = 18–22.
- **Promień:** `AppTheme.radius` = 14 (karty, panele). Pille = 999.
- **Karta:** `surface` + obwódka 1px `border` + radius 14. Tylko przez `AppTheme.cardDecoration()` lub motyw `Card` — nie ręcznie.

### 12.4 Komponenty (SSoT helpery — używać, nie klonować)
`AppTheme.cardDecoration()` · `AppTheme.statusPill(label, kind)` · `AppTheme.statusColor(kind)` · `AppTheme.boolStatus(bool)`. Pill = tło koloru @14% + obwódka @50% + kropka. Nagłówek sekcji = UPPERCASE, `caption`, letterSpacing 1.2, `textMuted`.

### 12.5 Stany ekranu (każdy ekran z danymi MUSI mieć 3)
1. **loading** — spinner w `accent` + krótki tekst `textMuted` (nie pusty ekran).
2. **error** — ikona `cloud_off` w `offline` + powód + przycisk „Spróbuj ponownie".
3. **empty** — ikona + jednozdaniowa zachęta (nie pusta lista).
Plus **pull-to-refresh** na każdym ekranie z danymi.

### 12.6 Zasada nadrzędna
„**Operator control room**": ciemno, gęsto informacyjnie, czytelnie, **dane > dekoracja**. Zero ozdobnych animacji (non-goal §1) — tylko mikro-przejścia stanów. To nie MVP — wykończenie ma być równe na wszystkich 9 ekranach.

---

## 13. Backlog / dodatki (PARKING — później, nie teraz)

> Wszystko nowe ląduje TU, nie w kodzie, dopóki standard (§12) nie jest dociągnięty na tym, co mamy. Kolejność = do ustalenia z Erykiem.

**Pomysły-dodatki (extras):**
- **Kolor-zakładki** *(pomysł Eryka, 2026-06-09)* — ikona „System" w dolnym pasku barwiona stanem zdrowia (zielony/bursztyn/czerwony) → kondycja Marii widoczna bez wchodzenia w ekran.
- Skeleton-loady zamiast spinnerów; lekka haptyka przy akcjach.

**Dokończenie danych (read-only):**
- ~~**Dashboard Etap 2b**~~ ✅ 2026-06-10 — „aktywne projekty" z konduktora (`/api/projects`) + „następny krok" z notki BUILD_NOW (`/api/build`); wariant „następny krok ze stratega" możliwy później, wymagałby nowego endpointu.
- **Żywe kafelki:** Pamięć (`/api/memory/query`, `/api/beliefs/recent`), Zadania (`/api/tasks`, `/api/learning/goals`), Dziennik (`/api/traces`), Ustawienia (`/api/user/profile`).

**Większe etapy (z §8):**
- ~~Chat na żywo (Etap 3)~~ ✅ 2026-06-10 · ~~`/api/projects`~~ ✅ 2026-06-10 (konduktor) + zakładka Budowa (`/api/build`) · Akcje/write (Etap 4) · Tryby czatu jako realne persony serwera (§4, jeśli wrócą) + `/api/files` write (Etap 5).
- **Dostęp poza WiFi:** Tailscale (prywatny tunel) + token API w `maria_ui` + natywny APK przez chmurę (mini PC nie ma Android SDK). (Etap 6 / dostęp zdalny.)
- Push: `proactive_notification` → natywne powiadomienia (FCM/local).

---

*Plik żyjący. Aktualizuj przy każdym zamkniętym etapie. SSoT dla projektu M.A.R.I.A. Mobile.*
