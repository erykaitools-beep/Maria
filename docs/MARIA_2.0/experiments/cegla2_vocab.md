# CEGŁA 2 — ZAMROŻONY SŁOWNIK PRYMITYWÓW OSNOWY (prereg, 2026-07-09)

> Zamrożone PRZED transpilacją (protokół BLUEPRINT 7.4.A). Zmiana tego pliku po rozpoczęciu
> transpilacji = złamanie prereg. Cel: zdefiniować SKOŃCZONY, DEKLARATYWNY zestaw operacji, nad którym
> wyraża się reguły-jako-dane taktycznego łańcucha Plannera K5. Jeśli wierne oddanie 1.0 wymaga czegoś
> spoza tej listy → to jest ESCAPE (i wynik cegły 2, patrz 7.4.A/7.4.E).

## Zasada nadrzędna: SUB-TURING

Słownik jest celowo NIE-Turing-zupełny: **brak pętli/rekurencji definiowanych przez użytkownika, brak
zmiennych mutowalnych, brak wywołań funkcji użytkownika.** Dozwolona jest tylko: ewaluacja wyrażeń nad
ramką, uporządkowane reguły (first-match), i JEDNA wbudowana forma iteracji ograniczonej (`fold-first`
po skończonej liście celów — modeluje pętlę PIVOT, nie jest programowalną pętlą). To gwarantuje, że
„escape ≈ 0" NIE jest trywialne (7.4.A pułapka Turing-zupełności).

## 1. Typy wartości
`num` (float), `bool`, `str`, `enum-action` (16 ActionType), `enum-goaltype` (learning/meta/user/maintenance),
`set[str]`, `list[goal]`, `null`. Bez typów złożonych definiowanych przez użytkownika.

## 2. Dostęp do pola ramki (`field`)
Odczyt (bez zapisu) nazwanego pola z ramki decyzji. Dozwolone ścieżki (zamrożone):
- Cel: `goal.priority`, `goal.created_at`, `goal.type`, `goal.deadline`, `goal.progress`,
  `goal.description`, `goal.metadata[<key>]` (key ∈ {forced_action_type, needs_fetch, source, topics,
  topic, theme_tag, metric, file_ids, fetched_file_ids, project_parent, deadline}).
- Snapshot: `snapshot.files_by_status[<s>]` (s ∈ {learning, learned, completed}), `snapshot.new_files_available`.
- Metryki: `metrics.retention_rate`.
- Środowisko/zegar: `now`, `is_learning_window`, `off_window_budget_remaining`, `deadline_mode`.
- Stan ukryty (z ramki, NIE odtwarzany na żywo — 7.4.C): `hidden.action_failures[<action:goal>]`
  (count,last_ts), `hidden.stuck_cooldowns[<goal>]`, `hidden.k7_history[<action>]` (timestampy),
  `hidden.strategic_blocked_goals`, `hidden.strategic_active`.
- Pola-proxy stanu zewnętrznego (patrz §6 ESCAPE): `ext.creative_should_reflect`,
  `ext.weak_topic_file_exists`, `ext.expert_topic_available`, `ext.k8_action` (K8 poza zakresem).

## 3. Arytmetyka (`num → num`)
`mul`, `add`, `sub`, `div`, `min`, `max`, `clamp(x, lo, hi)`. Stałe liczbowe dozwolone (zamrożone progi:
AGING_FACTOR 0.1, MAX_AGING 4.0, DEADLINE_* , retention 0.8, weak-belief 0.3, TTL 3600, thresholds).

## 4. Porównania i logika (`→ bool`)
`lt, le, gt, ge, eq, ne` (num/str), `and, or, not`, `is_null`, `nonempty` (list/str/set),
`in_set(x, <frozen-set>)`, `substr_any(str, <frozen-set>)` (dopasowanie podłańcucha, lowercase — dla
META_LEARNING_KEYWORDS), `truthy(field)`.

## 5. Formy sterujące (JEDYNE dozwolone)
- **`rules`**: uporządkowana lista `[{when: <bool-expr>, then: <action|subrule>}]` — FIRST MATCH wygrywa.
  Zero fallthrough-magii; ostatnia reguła bezwarunkowa (`when: true`) = default.
- **`map`**: tabela `{klucz: wartość}` + default (dla theme_tag→action, feasibility→bool).
- **`derived`**: nazwane wyrażenie pomocnicze (bez rekurencji; DAG, nie graf cykliczny) —
  np. `effective_priority`, `is_feasible`, `is_saturation_meta`, `is_fetch_handoff`.
- **`fold-first`**: nad `list[goal]` w kolejności rankingu, zwróć pierwszy cel, dla którego `rules`
  dają action ≠ NOOP i ≠ K7-blocked. To i TYLKO to modeluje pętlę PIVOT. Ograniczone (skończona lista,
  jeden przebieg, bez akumulatora).

## 6. ESCAPE — definicja binarna (liczy niezależny audytor, 7.4.A)
Decyzja jest ESCAPE, jeśli jej `action_type` NIE jest w pełni wyznaczony przez ewaluację powyższych
prymitywów nad ramką — tzn. reguła musiałaby wywołać z powrotem imperatywny kod 1.0. Trzy kandydaci
(stan zewnętrzny NIE-frame'owalny bez uruchomienia podsystemu 1.0):
- `_find_weak_topic_file` (query world_model o gaps confidence<0.3),
- `_pick_expert_topic` (budowa pytania z luk),
- `should_reflect` (creative module cooldown).
Reprezentujemy je jako pola-proxy `ext.*` (§2). **KLUCZOWE ROZSTRZYGNIĘCIE PREREG:** proxy liczy się jako
ESCAPE wtedy i tylko wtedy, gdy jego wartość NIE da się wyliczyć z pozostałych pól ramki (wymaga żywego
podsystemu). Audytor klasyfikuje każdy z 3 proxy jako escape/nie-escape na podstawie tego, czy jego
wejścia są w ramce. K8 (`ext.k8_action`) jest JAWNIE poza zakresem (7.4.C) — cykle K8-driven liczone
osobno, nie w mianowniku escape.

## 7. Czego NIE ma (gwarancja sub-Turing)
Brak: pętli while/for programowalnych, rekurencji, zmiennych mutowalnych, I/O, wywołań metod 1.0 innych
niż odczyt pól ramki, arytmetyki na stringach poza `substr_any`, definicji funkcji przez użytkownika.
