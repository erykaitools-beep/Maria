# Milestone 1: OperatorModel v1

> Implementation plan for Digital Human Roadmap, Faza 1.
> Scope: pierwszy krok - maly, konkretny, wdrazalny.

## 1. Scope v1

Przeksztalcenie obecnego `UserProfile` (flat list of facts + regex extraction) w **OperatorModel** z 5 wymiarami. v1 skupia sie na:

### IN SCOPE:

**A. Data model: 5-wymiarowy profil**
- `durable_facts` - structured: zawod, miasto, wiek, sprzet, jezyki (z confidence + source + timestamp)
- `preferences` - rozszerzenie istniejacego: quiet_hours, detail_level, proactive_contact, irytujace_zachowania
- `day_rhythm` - detected patterns: kiedy aktywny, kiedy pracuje, kiedy weekend, typowe godziny kontaktu
- `current_context` - volatile: "dzis mam deadline", "jestem na urlopie", "jestem chory" (auto-expire)
- `privacy_boundaries` - jawna lista: czego nie pytac, czego nie logowac (operator-defined, non-overridable)

**B. RhythmDetector**
- Analiza historii Telegram timestamps (proactive_contacts.jsonl + incoming messages)
- Wykrywanie: typowa pora wstawania, typowe godziny aktywnosci, weekday vs weekend pattern
- Wynik: `day_rhythm` w profilu, uzywany przez Proactive Contact (nie wysylaj gdy operator spi)

**C. PrivacyGuard**
- Operator definiuje granice via Telegram: `/privacy add <topic>`, `/privacy list`, `/privacy remove <topic>`
- Przed kazdym pytaniem ActiveLearnera: sprawdz czy temat nie jest w boundaries
- Przed kazdym zapisem do profilu: sprawdz czy nie narusza granicy
- Privacy boundaries sa NIENARUSZALNE - nawet jesli Maria mogłaby wywnioskować, nie robi tego

**D. Improved fact extraction**
- Rozszerzenie `learn_from_message()` o structured extraction do nowego modelu (nie flat list)
- Confidence scoring: jawne podanie = 1.0, inference z rozmowy = 0.6, pattern = 0.4
- Source tracking: "telegram:2026-04-12", "web_ui:chat", "explicit:/profile set"

**E. MorningBrief personalizacja**
- generators.py _morning_summary() uzywa OperatorModel:
  - greeting personalizowany pod rytm dnia
  - tresc filtrowana pod preferencje (detail_level)
  - nic nie wysylane gdy current_context = "urlop" lub "nie przeszkadzac"

**F. Telegram commands**
- `/profile` - ulepszone wyswietlanie (5 wymiarow)
- `/profile set <key> <value>` - jawne ustawienie faktu
- `/profile rhythm` - pokaz wykryty rytm dnia
- `/privacy add/list/remove` - zarzadzanie granicami prywatnosci
- `/context <text>` - ustaw aktualny kontekst ("dzis deadline", "urlop do piatku")

## 2. Explicitly OUT OF SCOPE

| Element | Dlaczego nie teraz |
|---------|-------------------|
| ActiveLearner (Maria pyta) | Wymaga NIM/LLM do generowania naturalnych pytan. Osobny milestone. |
| RelationshipTracker | "Od kiedy sie znamy, co wspólnie zrobilismy" - wartosc dodana, ale nie krytyczna dla v1 |
| ContextInference | Auto-wnioskowanie "operator zajety bo nie odpowiada" - ryzyko false positives, potrzebuje RhythmDetector danych z kilku tygodni |
| ConversationMemory integration | Auto-extraction z kondensacji rozmow - wymaga refactoru ConversationMemory, osobny milestone |
| Web UI /profile page | Juz istnieje, ale rozbudowa UI nie jest priorytetem v1 |
| Multi-language support | Maria mowi po polsku z Erykiem, wystarczy na teraz |

## 3. Files/modules to change

### Nowe pliki:
```
agent_core/operator/                    # NOWY pakiet
  __init__.py
  operator_model.py                     # OperatorModel class (zastepuje UserProfile jako primary)
  rhythm_detector.py                    # RhythmDetector - pattern extraction
  privacy_guard.py                      # PrivacyGuard - boundary enforcement
```

### Modyfikowane pliki:
```
agent_core/consciousness/user_profile.py  # Adapter: deleguje do OperatorModel, backward compat
agent_core/proactive/generators.py        # MorningBrief personalizacja
agent_core/telegram/bridge.py             # Nowe komendy: /privacy, /context, /profile rhythm
agent_core/modules/homeostasis_module.py  # Wiring: OperatorModel w SharedContext
agent_core/llm/master_prompt.py           # Kontekst z OperatorModel zamiast UserProfile
```

### Niezmieniane (backward compat via adapter):
```
agent_core/consciousness/user_profile.py  # get_name(), get_facts(), etc. nadal dzialaja
maria_ui/app.py                           # /api/user/profile endpoint bez zmian
```

## 4. New contracts/interfaces

### K14: OperatorModel

```python
class OperatorModel:
    """5-dimensional operator understanding with confidence scoring."""

    # -- Durable Facts --
    def set_fact(self, key: str, value: str, confidence: float = 1.0, source: str = "") -> None
    def get_fact(self, key: str) -> Optional[OperatorFact]  # {value, confidence, source, updated_at}
    def get_all_facts(self) -> Dict[str, OperatorFact]

    # -- Preferences --
    def set_preference(self, key: str, value: Any) -> None
    def get_preference(self, key: str, default: Any = None) -> Any

    # -- Day Rhythm --
    def get_rhythm(self) -> DayRhythm  # {typical_wake, typical_sleep, work_hours, weekend_pattern}
    def update_rhythm(self) -> None  # recalculate from interaction history
    def is_likely_active(self) -> bool  # based on current time + rhythm
    def is_likely_working(self) -> bool

    # -- Current Context --
    def set_context(self, text: str, expires_hours: int = 24) -> None
    def get_context(self) -> Optional[str]  # None if expired
    def clear_context(self) -> None

    # -- Privacy Boundaries --
    def add_boundary(self, topic: str) -> None
    def remove_boundary(self, topic: str) -> bool
    def get_boundaries(self) -> List[str]
    def is_allowed(self, topic: str) -> bool  # True if NOT in boundaries

    # -- Integration --
    def get_context_for_prompt(self) -> str  # for LLM system prompt
    def get_operator_brief(self) -> str  # human-readable summary
    def learn_from_message(self, message: str) -> int  # extract facts from text
```

### K14.2: RhythmDetector

```python
class RhythmDetector:
    """Temporal pattern extraction from interaction history."""

    def analyze(self, timestamps: List[float]) -> DayRhythm
    def detect_work_pattern(self, timestamps: List[float]) -> Optional[WorkPattern]
    def is_weekend_pattern(self, timestamps: List[float]) -> bool
```

### K14.3: PrivacyGuard

```python
class PrivacyGuard:
    """Hard boundaries, operator-defined, non-overridable."""

    def check(self, topic: str) -> bool  # True = allowed
    def add_boundary(self, topic: str) -> None
    def remove_boundary(self, topic: str) -> bool
    def get_boundaries(self) -> List[str]
```

## 5. Data model

### Nowy format `meta_data/operator_model.json`:

```json
{
  "version": 2,
  "durable_facts": {
    "name": {"value": "Eryk", "confidence": 1.0, "source": "explicit", "updated_at": "2026-04-10"},
    "age": {"value": "32", "confidence": 1.0, "source": "telegram:message", "updated_at": "2026-04-10"},
    "job": {"value": "plytkarz", "confidence": 1.0, "source": "telegram:message", "updated_at": "2026-04-10"},
    "job_location": {"value": "Niemcy", "confidence": 1.0, "source": "telegram:message", "updated_at": "2026-04-10"},
    "city": {"value": null, "confidence": 0.0, "source": "", "updated_at": ""},
    "language": {"value": "pl", "confidence": 1.0, "source": "default", "updated_at": "2026-04-10"}
  },
  "preferences": {
    "response_style": "casual",
    "autonomy_level": "medium",
    "notify_channel": "telegram",
    "detail_level": "normal",
    "quiet_hours": [23, 6]
  },
  "interests": ["programowanie", "fizyka"],
  "day_rhythm": {
    "typical_wake_hour": 7,
    "typical_sleep_hour": 23,
    "work_hours": [9, 17],
    "weekend_days": [5, 6],
    "confidence": 0.4,
    "sample_count": 12,
    "last_analyzed": "2026-04-12"
  },
  "current_context": {
    "text": null,
    "set_at": null,
    "expires_at": null
  },
  "privacy_boundaries": [],
  "stats": {
    "first_seen": "2026-04-10T17:44:37",
    "last_seen": "2026-04-12T10:30:00",
    "total_messages": 15,
    "sessions_count": 3
  },
  "updated_at": "2026-04-12T10:30:00"
}
```

### Migracja z user_profile.json:
- Jednorazowa: przy pierwszym uzyciu OperatorModel, jesli operator_model.json nie istnieje, zaladuj user_profile.json i przekonwertuj
- user_profile.json NIE jest usuwane (backward compat)
- UserProfile class staje sie adapterem: deleguje do OperatorModel
- Istniejace `facts` list -> parsowanie do structured `durable_facts` (regex: "mam 32lata" -> age=32, "pracuje jako X" -> job=X)

## 6. Migration impact

| Komponent | Wplyw | Dzialanie |
|-----------|-------|-----------|
| UserProfile | Adapter pattern | Deleguje do OperatorModel, API bez zmian |
| Web UI /profile | Bez zmian | Endpoint nadal uzywa UserProfile (adapter) |
| Telegram /profile | Rozszerzony | Nowe subkomendy, istniejace dzialaja |
| MasterPrompt | Minimalny | `get_context_for_prompt()` z OperatorModel zamiast UserProfile |
| OllamaBrain | Zero | Uzywa `get_context_for_prompt()` - interfejs bez zmian |
| Proactive generators | Rozszerzony | Dodatkowe dane z OperatorModel |
| Planner | Zero | Nie uzywa UserProfile bezposrednio |
| ConversationMemory | Zero | Auto-extraction w osobnym milestone |

**Ryzyko migracji: NISKIE.** Adapter pattern gwarantuje ze nic sie nie psuje.

## 7. Tests to add/update

### Nowe testy (~80-100):

```
agent_core/tests/test_operator_model.py     # ~40 testow
  - test_set_get_fact_with_confidence
  - test_fact_source_tracking
  - test_migration_from_user_profile
  - test_structured_extraction (age, job, city from text)
  - test_get_context_for_prompt_v2
  - test_get_operator_brief
  - test_current_context_set_expire_clear
  - test_current_context_auto_expire
  - test_preferences_crud
  - test_interests_crud (backward compat)
  - test_persistence_atomic_write
  - test_cross_process_reload
  - test_thread_safety

agent_core/tests/test_rhythm_detector.py    # ~20 testow
  - test_detect_wake_time_from_timestamps
  - test_detect_work_hours
  - test_weekend_vs_weekday
  - test_is_likely_active
  - test_insufficient_data_returns_defaults
  - test_confidence_scales_with_samples

agent_core/tests/test_privacy_guard.py      # ~15 testow
  - test_add_remove_boundary
  - test_check_allowed
  - test_check_blocked
  - test_substring_matching
  - test_case_insensitive
  - test_persistence
  - test_empty_boundaries_allows_all

agent_core/tests/test_operator_telegram.py  # ~15 testow
  - test_privacy_add_command
  - test_privacy_list_command
  - test_context_set_command
  - test_profile_rhythm_command
  - test_profile_set_command
```

### Zaktualizowane testy:
```
agent_core/tests/test_proactive.py          # morning brief personalizacja
agent_core/tests/test_user_profile.py       # adapter deleguje do OperatorModel
```

## 8. Risks

| Ryzyko | Prawdopodobienstwo | Wplyw | Mitygacja |
|--------|-------------------|-------|-----------|
| Profil rozsynchronizowany miedzy procesami | Srednie | Sredni | mtime check (juz istnieje w UserProfile), atomic writes |
| RhythmDetector za malo danych | Wysokie (start) | Niski | Defaults + confidence scoring, "unknown" jest OK |
| Fact extraction false positives | Srednie | Niski | Confidence < 1.0 dla inferencji, operator moze usunac |
| Migration psuje istniejacy profil | Niskie | Wysoki | Adapter pattern, user_profile.json nietkniete, testy migracji |
| Privacy boundaries obchodzone | Niskie | Wysoki | Guard sprawdzany PRZED kazdym zapisem i pytaniem, testy |
| Over-engineering structured facts | Srednie | Sredni | Start z 6-8 kluczami (name, age, job, city, job_location, language), reszta jako freeform |

## 9. Success criteria

### Minimum Viable:
1. `OperatorModel` zaladowany z migracja z istniejacego profilu Eryka
2. `/profile` na Telegramie pokazuje 5 wymiarow czytelnie
3. `/context "mam deadline"` dziala i wpływa na zachowanie Marii (np. mniej proaktywnych wiadomosci)
4. `/privacy add/list/remove` dziala
5. RhythmDetector zwraca COKOLWIEK z historii kontaktow (nawet "za malo danych, uzywam domyslnych")
6. Poranna wiadomosc mowi "Dzien dobry, Eryk!" zamiast "Dzien dobry, Operator!" (juz dziala, ale potwierdz)
7. Wszystkie istniejace testy UserProfile NADAL przechodza (adapter)

### Stretch:
8. Morning brief pomija sekcje gdy `current_context` = "urlop"
9. Proactive scheduler respektuje `day_rhythm.typical_wake_hour` (nie wysyłaj przed)
10. `/profile rhythm` pokazuje wykryty wzorzec

## 10. Fake progress to avoid

| Pulapka | Dlaczego to nie jest prawdziwy postep |
|---------|--------------------------------------|
| Formularz onboardingowy z 20 polami | Operator nie bedzie go wypelnial. Profil musi rosnac z rozmow. |
| "Smart" NLP extraction bez testow | Regex z testami > fancy NLP z false positives. Start prosty. |
| Dashboard profilu w Web UI | Ladne ale nikt nie uzywa. Telegram /profile wystarczy. |
| RhythmDetector z ML | Za malo danych. Mediana timestamps > random forest. |
| "Personality engine" | Maria juz ma osobowosc (TraitEvolver). Nie buduj drugiej. |
| Privacy "AI-based detection" | Granice sa JAWNE i operator-defined. Nie zgaduj. |

---

## Kolejnosc implementacji

1. **OperatorModel class + data model + migration** (fundament)
2. **PrivacyGuard** (musi istniec PRZED jakimkolwiek uczeniem sie o operatorze)
3. **Improved fact extraction** (structured facts z confidence)
4. **RhythmDetector** (analiza historii timestamps)
5. **Telegram commands** (/privacy, /context, /profile rhythm)
6. **MorningBrief personalizacja** (uzyj nowego modelu)
7. **Wiring** (homeostasis_module, SharedContext, adapter)
8. **Testy + migration test na produkcyjnym profilu**

Szacunek: 2-3 sesje robocze.

---

*Data: 2026-04-12. Milestone 1 z Digital Human Roadmap Faza 1.*
