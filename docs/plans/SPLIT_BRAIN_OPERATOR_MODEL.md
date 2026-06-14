# Plan #5 — Split-brain OperatorModel ↔ UserProfile (LOCAL)

> Recon 2026-05-30. Kierunek wybrany przez Eryka: **OperatorModel = jedyne źródło prawdy.**
> Status: **PLANK 1 = OBSERVED ✅** (2026-05-30 13:36). Decyzja: **Opcja B (wspólny singleton)**.

## PLANK 1 OBSERVED (2026-05-30 13:36)
Eryk napisał w Web UI "W wolnym czasie lubię spać" (`conversation_history.jsonl` → `source: web`).
`operator_model.json` urósł w tej samej sekundzie: `interests: [...,'spać']`, mtime+updated_at 13:36:20.
Dowód że czat UI karmi teraz wspólny OperatorModel. Telegram wykluczony (brak pollów 13:3x).

**Namiar dla Planka 3 (legacy write znaleziony):** `app.py:575-580` wpina osobny `UserProfile()`
do mózgu UI (`brain.set_user_profile`), więc mózg uczy się też do `user_profile.json` (też dostał
"spać" o 13:36:20). To jest to drugie przejście do skasowania w P3. Oba pliki dziś niezależne
(operator_model.json migruje z user_profile.json TYLKO przy pierwszym init — brak clobberu).

## Recon zamknięty (2026-05-30) — niespodzianka
Zakładaliśmy dostęp UI→demon przez `SharedContext.instance()`. **Tego nie ma** — `SharedContext`
to zwykły `@dataclass`, zero singletona/`instance()`. Czyli każde `SharedContext.instance()` w
`app.py` cicho zwraca None (martwa obrona). **Demon i UI NIE dzielą obiektów w pamięci** — gadają
tylko przez pliki. UI ma nawet własny mózg Ollama (`_maria_brain`, app.py:103/547). To ten sam
korzeń co "UI = drugi mózg".

Konsekwencja: lazy-init w UI (Opcja A) ma cichą dziurę — demon ma zapisy (`set_preference`,
`add_interest`, `set_fact`) które NIE wołają `_reload_if_changed()` przed `_save()`, więc stary
in-memory stan demona może nadpisać fakt zapisany z UI. **Eryk wybrał Opcję B: jeden wspólny
OperatorModel w pamięci** (jeden proces = jeden organizm). Realizacja: `get_operator_model()`
singleton w `operator_model.py`; demon i UI oba przez niego.

## Problem (audyt v2 #3, v1)
Dwa osobne liczniki tożsamości operatora, dwa pliki, brak synchronizacji:
- **OperatorModel** (`agent_core/operator/operator_model.py`, 910 linii, `meta_data/operator_model.json`)
  — bogaty, 5-wymiarowy. Karmiony przez **stronę demona**: Telegram (`core.py:1181 om.learn_from_message`),
  homeostaza, weather/salience, perception, environment. Sam deklaruje "replaces flat UserProfile".
- **UserProfile** (`agent_core/consciousness/user_profile.py`, ~400 linii, `meta_data/user_profile.json`)
  — prostszy, flat. Karmiony/czytany przez **stronę UI/czatu**: Web UI (`app.py`), `master_prompt.py`,
  onboarding, `maria.py:210` (shutdown).
- Skutek: czego uczysz Marię w Web UI nie dociera do jej "operacyjnego mózgu" (OperatorModel).
  Audyt: "Web UI nie karmi operator_model (grep learn_from_message w app.py = 0)".

## Recon zgodności (zrobiony)
OperatorModel ma **13 z 15** metod, których świat woła od UserProfile:
- MA: get_name, get_summary_for_prompt, get_interests, learn_from_user_facts, get_name_confidence,
  update_field, learn_from_message, set_name, update_name_confidence, to_dict, get_summary,
  get_language, get_summary_for_prompt_compact
- **BRAK: get_preferences, learn_from_facts** (po 1 call-site każda — dodać do OperatorModel)

OperatorModel auto-migruje z user_profile.json przy pierwszym użyciu (`_migrate_from_user_profile`, linia 274).

## ⚠️ KLUCZOWE RYZYKO (znalezione, blokuje "jeden ruch")
`to_dict()` ma **inny kształt** w obu — Web UI front-end na tym polega:
- UserProfile.to_dict: `identity / preferences / facts / schedule / channels / stats`
- OperatorModel.to_dict: `durable_facts / preferences / day_rhythm / current_context / privacy / confidence_summary`
  **KOREKTA (recon):** top-level serializer OperatorModel to `get_full_profile()` (linia 886) +
  `get_summary()` (882), NIE `to_dict` — te trzy `to_dict` w pliku są na subklasach
  (OperatorFact/DayRhythm/CurrentContext). Przy Planku 3 zweryfikować dokładny kształt `get_full_profile()`.

Web UI `/api/user_profile` (app.py ~3761) zwraca UserProfile.to_dict() → front-end oczekuje kształtu UserProfile.
**Nie wolno** zrobić UserProfile→cienki-adapter w jednym ruchu — zepsuje to widok UI. Trzeba mapować kształt.

## Plan plank-by-plank (każdy = osobny restart + weryfikacja w logach)

### Plank 1 — KOD GOTOWY (Opcja B), czeka na OBSERVED
Most UI→OperatorModel przez **wspólny singleton**:
- `operator_model.py`: `get_operator_model()` (+ `reset_operator_model_singleton()` do testów) —
  jeden proces-wide instancja, thread-safe (`_SINGLETON_LOCK`).
- `homeostasis_module.py:129`: demon woła `get_operator_model()` zamiast `OperatorModel()`.
- `app.py handle_chat_message` (~2073): `get_operator_model().learn_from_message(user_message)`,
  try/except + `print("[UI][WARN]")` (app.py nie ma loggera).
- Testy: +3 (`TestSharedSingleton`) — same instance / shared mutation / reset. 70/70 operator zielone.
- Zero zmian w to_dict / front-endzie / API. Odwracalne.
- **OBSERVED (TODO po restarcie):** gadasz w UI fakt (np. "mieszkam w X") → `operator_model.json`
  rośnie (mtime + nowy durable_fact). To samo źródło widzi Telegram/autonomia.

### Plank 2 — OBSERVED ✅ (2026-05-30 13:50)
Plan zakładał master_prompt.py — recon pokazał inaczej:
- **homeostasis_module.py reads = już OperatorModel** (`ctx.user_profile = operator_model`, linia 130).
- **master_prompt.py NIE czyta profilu-obiektu** — imię idzie z ENV `MARIA_OPERATOR_NAME`
  (`_OPERATOR_NAME_DEFAULT`), a profil wchodzi jako string `user_context` budowany przez mózg.
- **Prawdziwy fix = wiring mózgu UI.** `OllamaBrain` (`models/ollama_brain.py`) czyta profil w
  `_build_system_prompt` (`get_context_for_prompt`, 247) i uczy się w `think()` (`learn_from_message`
  + `record_interaction`, 397-398). UI wpinało tu świeży `UserProfile()` (app.py:578) → stąd
  duplikat user_profile.json. **Zmiana: app.py:578 `UserProfile()` → `get_operator_model()`** (wzór
  jak demon, homeostasis:166). OperatorModel ma wszystkie 3 metody, oba call-site w try/except.
- **OBSERVED:** po restarcie czat UI → operator_model.json ruszył, user_profile.json zamrożony
  (rano oba rosły). Mózg odpowiedział (think() ran). Commit `70f5577`.
- Uwaga: explicit call z Planka 1 (handle_chat_message) zostaje jako safety-net gdy brain=None;
  drobna redundancja (podwójny learn do tej samej instancji) — nieszkodliwa.

### Plank 3 (UserProfile → adapter, z mapowaniem kształtu)
UserProfile staje się cienką fasadą nad OperatorModel. `to_dict()` w adapterze **mapuje** OperatorModel
→ kształt UserProfile (identity/preferences/facts/...), żeby Web UI front-end działał bez zmian.
Dodać brakujące get_preferences/learn_from_facts. `user_profile.json` znika jako osobne źródło.
Alternatywa: zaktualizować front-end UI do kształtu OperatorModel (większy zakres, ale czystsze).

## Uwagi
- Duży klocek na żywym UI — NIE batchować, plank po planku, restart + log po każdym.
- Eryk: "głos wszędzie" = ten split musi zniknąć, żeby jeden organ (np. głos) wpięty raz działał
  w Telegramie i UI tak samo. [[project-organ-architecture-one-truth]].
