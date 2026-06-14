# Faza J — Werdykt API Brain Test

> **Status:** CLOSED (werdykt: MIXED — silnik pomaga, strukturalne luki pozostają)
> **Data werdyktu:** 2026-05-16
> **Okres testu:** 2026-04-18 → 2026-05-10 (glm-5.1, 22 dni) + 2026-05-10 → 2026-05-16 (nemotron-49b, 6 dni)
> **Plan referencji:** ROADMAP.md v2.1 Faza J (deploy 2026-04-18, werdykt ~2026-05-01)

## TL;DR

Faza J miała sprawdzić czy architektura Marii skaluje się do mocniejszego silnika. Werdykt **MIXED**: silnik daje wymierne korzyści (latency -36%, K13 quality, 0% errors w glm-5.1), ale **nie eliminuje strukturalnych luk** (exam fails 100%, konfabulacja w chat path 3 generacje, planner stuck-loops). Wniosek operacyjny: **kontynuujemy Statek Teseusza (Faza K)** z naciskiem na deski poza routing — Planner v2 i symboliczny World Model. Silnik nie zastąpi reform architektonicznych.

## Kontekst — co Faza J miała sprawdzić

Hipoteza wyjściowa: Obecny silnik (Ollama llama3.1:8b) może być bottleneckiem. Jeśli swap na mocniejszy LLM da wymierne polepszenie w K12/K13/exam/ExpertBridge, architektura jest OK i bottleneck leży w silniku → RAM upgrade + lokalny 30B-A3B. Jeśli nie ma różnicy, architektura ma luki i wymaga redesignu desk (Statek Teseusza).

Zaplanowane metryki:
- Jakość K13 creative tensions (NIM-powered)
- Sharpness K12 self-analysis recommendations
- TeacherAgent exam scores
- ExpertBridge query quality
- Latency, token burn, fallback rate
- Polish language quality

## Co się stało faktycznie

| Data | Wydarzenie |
|------|-----------|
| 2026-04-18 | Deploy z-ai/glm-5.1 jako NIM_PRIMARY (thinking model, NIM_TIMEOUT=120s, daily limit 500k tokenów) |
| 2026-04-21 | Architecture findings — glm-5.1 wymaga `temperature=1.0` + `force_json` dla strukturalnych odpowiedzi |
| 2026-04-23/24 | Audyt B, C1 NIM-first planner shipped |
| 2026-04-26 | D-board full clearance (D1-D4 done), ANALYTICAL classification split |
| 2026-05-01 | (planowany werdykt) — nie napisany, ekstended observation |
| 2026-05-10 | **glm-5.1 server-side padł** (60s+ timeouts, 2/25 success rate w probe). Switch do `nvidia/llama-3.3-nemotron-super-49b-v1.5` (443ms probe). NIM-first router gated via `NIM_PRIMARY_ROLES`. |
| 2026-05-13/14 | 24h autonomy test — pierwszy real-world test dojrzałości, verdict 4/5 PASS, plank-by-plank revert |
| 2026-05-14/15 | Postmortem 24h test: 5 architectural bugs flagowanych, 4 closed (Bug 1 exam parser + Bugs 2/3/4/5 chat path) |
| 2026-05-16 | Werdykt formalny — ten dokument |

## Metryki

Źródło: `meta_data/llm_tape.jsonl` (6499 entries), `meta_data/self_analysis_reports.jsonl` (281), `meta_data/creative_events.jsonl` (4893), `meta_data/action_audit.jsonl` (450, rotated od 2026-05-13).

### Latency NIM calls (successful only)

| Model | n calls | p50 | p90 | mean | max |
|-------|---------|-----|-----|------|-----|
| z-ai/glm-5.1 | 2291 | **83.0s** | 165.2s | 91.4s | 239.3s |
| nvidia/nemotron-49b | 2477 | **53.0s** | 122.8s | 62.5s | 227.5s |

Nemotron jest **36% szybszy** w p50, 26% szybszy w mean. Oba modele są **znacznie wolniejsze niż Ollama llama3.1:8b** lokalnie (zwykle 10-30s zależnie od długości promptu). NIM HTTP roundtrip + thinking overhead = strukturalny narzut, nie eliminowalny przez wymianę modelu.

### Stability (error rate)

| Model + Rola | n calls | errors | error % |
|--------------|---------|--------|---------|
| glm-5.1 / learning | 1610 | 0 | **0.0%** |
| glm-5.1 / planner | 612 | 0 | **0.0%** |
| nemotron / learning | 2365 | 111 | **4.7%** |
| nemotron / planner | 274 | 51 | **18.6%** |

glm-5.1 był **bardzo stabilny** dopóki nie padł server-side (catastrophic outage 2026-05-10). Nemotron-49b ma wymierny error rate, zwłaszcza w roli planner (18.6%). Lokalny llama3.1:8b ma 201 errors w 1432 calls = 14% — porównywalne.

### Volume (skala wykorzystania)

| Okres | NIM Total | K12 reports | Creative events |
|-------|-----------|-------------|-----------------|
| pre_J (Ollama only) | – | 112 | – |
| glm-5.1 (04-18 → 05-10, 22 dni) | 2222 calls | 118 | 117 |
| nemotron (05-10 → 05-16, 6 dni) | 2639 calls | 51 | 4776 |

Volume po switch wzrósł nieprporcjonalnie: K12 z 118 → 51 (-57%), creative events z 117 → 4776 (+40×). Częściowo wyjaśnia to:
- 4776 to wszystkie zdarzenia w schema `event/timestamp/payload`, nie tylko meta-goals (typ poszerzony)
- K12 frequency obniżona przez post-postmortem zmiany cycle frequency
- Faktyczna intensywność reasoning per okres porównywalna

### Exam (TeacherAgent learning outcomes)

`action_audit.jsonl` został zrotowany — najwcześniejszy wpis 2026-05-13 23:37 UTC. Dla okresu glm-5.1 (04-18 → 05-10) **brak danych** o egzaminach w obecnym audit log (zrotowane archive może być w `meta_data/audit_reports/` — wszystkie z 2026-04-09).

Dla okresu post-rotacji (05-13 → 05-15):
- Total exam attempts: 153
- Successful: 0 (**100% FAIL**)

Przyczyna ustalona w postmortem 2026-05-14: **Bug 1 (exam parser)** — `exam_agent` nie umiał sparsować odpowiedzi LLM gdy NIM/Ollama zwracał strukturę markdown zamiast JSON. Fix wdrożony 2026-05-15 19:04 UTC (commit `2f55e47` force_json kwarg + markdown Q&A fallback). Verify live czeka na okno nauki 2026-05-16 9-11 Berlin (3 próby między 19:04-19:37 UTC były pre-fix pid; aktualny pid 4193268 ma fix ale jeszcze nie próbował exam).

**Implikacja:** exam fail rate nie jest miernikiem silnika. To bug parsera + downstream missed evaluation. Po fix powinien dramatycznie wzrosnąć success rate niezależnie od silnika.

### Konfabulacja (chat path quality)

Postmortem 2026-05-14 i pre-fix obserwacje:

| Generacja | Typ | Przykład | Status fix |
|-----------|-----|----------|------------|
| 1.0 | Pełna fabrykacja | "Wykonałam akcję X" gdy zero w audit | Layer 2+3 detector (commit `efe76ed`) |
| 2.0 | 3rd-party past attribution | "Musiałem powiedzieć planerowi co chcę" | detect_third_party_claim |
| 3.0 | Decorative prefix nad prawdą | "Widzę w logach... (pliki: 386)" gdzie 386 = prawda | Layer 1 master_prompt patch (limited skuteczność — wytrenowane nawyki LLM) |

**Konfabulacja nie znika ze zmianą silnika.** glm-5.1 i nemotron-49b oba ją produkują. Po 24h test (Plan B dialog 2026-05-14) Maria 3× konfabulowała akcje. Po fixach 2026-05-15 charakter zmienił się z malicious fabrication na decorative-but-true.

**Implikacja:** konfabulacja jest własnością prompt context delivery i wytrenowanych frazes LLM, nie własnością silnika. Reform musi zachodzić w prompt engineering + post-processing detector, nie wymianie modelu.

### K12 sharpness (subjective, ale relevant)

Wszystkie 281 K12 reports zapisane z `model: ?` (pole nie zarejestrowane). Nie da się ilościowo porównać między glm-5.1 a nemotron-49b. Subiektywna ocena ze strony Eryka (z notatek):
- glm-5.1: "31% strategic recs" (notatka 2026-05-10) — mierzono actionability
- nemotron: za wcześnie na wniosek (6 dni, 51 raportów)

### Planner stuck-loop

Z 2026-04-19 incydent: `mg-a0128 628× evaluate na 14h` — planner zaplątał się w ewaluacji bez progresji do akcji. Z designu Planner v2 (`docs/plans/DESIGN_PLANNER_V2.md`):
> Rule-based, stuck-in-evaluate-loop, brak LLM guidance dla nowych sytuacji.

Po deploy NIM-first planner (2026-04-23/24) z silniejszym silnikiem stuck-loop pojawia się **rzadziej** ale **nadal istnieje** — to deficyt architektury planner (brak progress signal, brak escape condition), nie deficyt silnika.

## Co silnik POMÓGŁ

1. **Latency -36%** w p50 (nemotron vs glm-5.1). NIM jest wciąż wolniejszy niż Ollama lokalnie, ale w obrębie NIM nemotron jest mierzalnie szybszy.
2. **Stability glm-5.1 = 0% errors** w 2222 calls przez 22 dni — wyższa niż Ollama lokalna (14% errors). Catastrophic outage 2026-05-10 to nie błąd modelu, to NIM/server problem.
3. **K13 creative quality** — Eryk subiektywnie oceniał wyższą jakość tension detection i meta-goals. Trudno mierzalne ilościowo bez user study.
4. **Architektura nie pęka pod nowym silnikiem** — żaden moduł K1-K13 nie wymagał structural rewrite dla glm-5.1 ani nemotron-49b. Routing przez `master_prompt.py` + `LLMManager` zniwelował różnice. To **walidacja designu Marii** — model swap jest pierwszoplanową operacją, nie projektem.

## Co silnik NIE POMÓGŁ

1. **Exam parser bug (Bug 1)** — 100% FAIL niezależnie od modelu. Strukturalna luka w parserze, nie LLM output quality.
2. **Konfabulacja chat path (3 generacje)** — glm-5.1 i nemotron oba fabrykują przeszłe akcje, oba używają "Widzę w logach" decorative prefix bez evidence. Reform wymaga prompt engineering + detector, nie wymiany modelu.
3. **Planner stuck-loop** — Mocniejszy silnik zmniejsza częstotliwość ale nie eliminuje. Deficyt to brak progress signal w planner engine.
4. **Asymetria user→goal vs maria→goal** — postmortem flag 2026-05-14 — chat ścieżka nie tworzy goali z 1st person Maria deklaracji. Bug logiki integracji, nie LLM.
5. **K7 effector restriction** — niezależnie od silnika, 24h test pokazał 0 effector calls przez całą dobę. To kwestia authority/gating, nie inteligencji silnika.
6. **Latency NIM 50-90s** — strukturalny narzut HTTP + thinking. Lokalny silnik (Ollama 10-30s) jest **3× szybszy** w p50. Mocniejszy NIM nie kompensuje.

## Werdykt — formalna decyzja

**MIXED — silnik pomaga w wymiernych obszarach (latency, stability dopóki dostępny, K13 quality), ale strukturalne luki Marii leżą POZA silnikiem.** Inwestycja w lokalny 30B-A3B nie rozwiąże exam parser bug, konfabulacji chat path, planner stuck-loops, asymetrii goal creation.

Kierunki działania:

### Kontynuacja Statek Teseusza (Faza K) — POTWIERDZONA

Wszystkie 4 deski Fazy K trzymają zasadność:
- **Deska #1: IntentRouter** — `/do pogoda` → WeatherSensor zamiast OpenClaw, nie zależy od silnika
- **Deska #2: Planner v2** — adresuje stuck-loop niezależnie od silnika
- **Deska #3: Symboliczny World Model** — reasoning bez LLM w pętli, redukuje zależność od silnika
- **Deska #4: warunkowa z #3**

### Wnioski dla strategii LLM

- **NIM = przydatne ale nie wystarczające.** Nemotron-49b zostaje jako EXTERNAL primary do `NIM_PRIMARY_ROLES`. Daily budget 750k / monthly 15M (zaktualizowany z 500k dziennego z czasu glm-5.1).
- **Ollama llama3.1:8b zostaje** jako lokalny executor + fallback. Mass operations (chat, planner main loop) korzystają z lokalnej szybkości.
- **Hybrid LLM strategy** (project_llm_strategy.md) potwierdzona — local primary, NIM jako "mentor/auditor" dla complex reasoning.
- **Anti-goal trzyma:** brak crutch na paid models. Maria musi działać offline (NIM outage 2026-05-10 pokazał ryzyko).

### Reform priority post-werdykt

Te 4 obszary nie są w Fazie K, ale wymagają osobnej uwagi:

1. **Konfabulacja Layer 1 prompt patch** — w Layer 1 master_prompt nadal LLM używa "Widzę w logach" decorative gdy zakaz. Trzeba spróbować twardsze: explicit `[BRAK_EVIDENCE]` token wymóg + post-processing strip.
2. **Asymetria user↔maria goal creation** — chat path musi traktować Maria 1st-person deklaracje analogicznie do user requestów (LLM intent + USER goal creation). Bug 3/5 partially fixed, integracja nie zamknięta.
3. **Planner stuck-loop escape condition** — niezależna od Planner v2 cutover. Quick fix: max 5 evaluate per goal-tick, after that force action selection or escalate to RESTRICTED.
4. **K7 effector authority calibration** — 24h test pokazał 0 effector calls. Plank up z RESTRICTED→GUARDED na effector (Maria stan post-revert) trzymać dłużej, monitorować safety w cyklu 1-2 tyg.

## Implikacje dla Fazy K planning

| Pierwotny plan | Reality | Update |
|---------------|---------|--------|
| M13 IntentRouter cutover ~2026-05-08 | Nie zaczęte | Re-target M13 → 2026-05-29 (Faza K rev 2) |
| M14 Planner v2 cutover ~2026-05-22 | Tylko design doc | Re-target M14 → 2026-06-12 |
| M15 Deska #3 (zależna od werdyktu J) | n/a | **DECYZJA werdyktu J: Symboliczny World Model** (silnik pomógł częściowo, ale to nie usunęło need for reasoning bez LLM w pętli) |
| Deska #4 | warunkowa z #3 | Planner v2 full cutover (ale szkielet z M14 musi być gotowy najpierw) |

Plus: deski zrobione **spoza pierwotnego planu** w okresie Fazy J (2026-04-22 → 2026-05-16) → do `docs/PROGRESS_LOG.md`.

## Follow-up

- [ ] Eryk: review werdyktu i akceptacja/dyskusja przed land ROADMAP.md v2.2
- [ ] Update `docs/ROADMAP.md` — Faza J z IN PROGRESS → COMPLETE (link do tego werdyktu)
- [ ] Utworzyć `docs/PROGRESS_LOG.md` z desk reality (Most #1, Most #2, B0, 24h test, Skills)
- [ ] Dodać Fazę M (Procedural Memory / Skills) jako nową fazę
- [ ] Verify Bug 1 fix w live runtime po oknie nauki 2026-05-16 9-11 Berlin (osobny todo)
- [ ] Decision: czy `model: ?` w K12 reports warto retroactively naprawić (audit pole `metadata.model` w przyszłych raportach)
- [ ] Konfabulacja Layer 1 prompt patch — strong-form (osobna sesja)

---

*Werdykt napisany 2026-05-16. Dane: llm_tape (6499), self_analysis_reports (281), creative_events (4893), action_audit (450 rotated). Notatki źródłowe: claude_notes/2026-05-10*, 2026-05-14*, 2026-05-15*.*
