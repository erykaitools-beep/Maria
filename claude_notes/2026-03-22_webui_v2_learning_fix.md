# Sesja 2026-03-22 (2/2) - Web UI v2 + Learning Pipeline Fixes

## Web UI v2 Metaoperator Panel

Kompletny refactor z prototypu v0.5 do panelu operatorskiego:
- base.html: Jinja2 base z topbar + blocks (zero duplikacji CSS/JS)
- maria_ui.css: design system (28 komponentow, dark premium, ~900 linii)
- 5 extracted JS files: maria_ui.js, status.js, chat.js, experiments.js, architecture.js
- Status page: 8 paneli (System, Models/Routing, OpenClaw, Homeostasis, Planner+Human Gate, Memory+Integrity, Event Stream+Filters, Identity+Traits)
- 7 nowych helperow w app.py dla danych statusu

Eryk mial bardzo szczegolowa wizje: desktop-first, wysoka gestosc danych, operator console feel.
ChatGPT pomagal mu w projektowaniu. 19 punktow feedbacku - wszystkie wdrozone.

## OpenClaw health_check bug

Nasz nowy status panel pollowal OpenClaw health_check() co 10s.
health_check() wywoluje `openclaw nodes run -- echo ok` -> gateway laduje qwen2.5:3b (3GB, 6 CPU cores).
Razem z llama3.1:8b = 100% CPU -> health score 83% -> 60%.

Fix: pgrep -f openclaw.*gateway zamiast health_check().
Dwa miejsca: app.py (_get_openclaw_data) i homeostasis_module.py (init).

Lekcja: monitoring nie moze byc ciezszy niz to co monitoruje.

## Learning Pipeline - llama3.1:8b nie zwraca JSON

Maria utknela na web_wiki_jezyk_japonski.txt (chunk 2, 20+ min fail loop).
Przyczyna: llama3.1:8b non-deterministycznie ignoruje "Odpowiedz w JSON" i zwraca markdown.

Probowalismy:
1. Fix JSON parser (backticks gdziekolwiek) - czescowo pomoglo
2. format:"json" w Ollama API - nie pomoglo bo teacher uzywa brain._ask_once() nie call_ollama()
3. Eryk zaproponowal: "dajmy Marii mozliwosc uczenia sie z markdown"

Fix: _parse_markdown_to_learning_dict() - fallback parser markdown -> dict.
Rozpoznaje sekcje (Streszczenie, Kluczowe punkty, Tagi, Pytania), bullet pointy, bold.
Aktywuje sie automatycznie gdy JSON parse failuje.

Rezultat: Maria przyswoila 12/12 chunkow materialu o modelach jezykowych w 17 min.

## Obserwacje

- Daemon nie przeladowuje modulow po zmianie pliku - trzeba kill + restart
- __pycache__ bywa uporczywy - PYTHONDONTWRITEBYTECODE=1 pomaga
- OllamaBrain._ask_once() nie uzywa call_ollama() - osobna sciezka (ollama.chat)
- Planner retriggeruje learn co minute na failing chunku - brak backoff/skip
- Eryk ma problem z haslem deployadmin (nie moze restartowac serwisow)
- Teacher nie przekazuje file_id do learn_next_chunk - planner wybiera plik, ale learn bierze sam

## Pomysly na przyszlosc

- Backoff na failing chunks (po N probach -> skip lub mark as hard_topic)
- Teacher powinien przekazywac file_id do learn_next_chunk (teraz ignorowany)
- Dense mode w UI (CSS custom properties juz gotowe)
- Sidebar w UI (layout przygotowany: mo-page--with-sidebar)
- Analiza egzaminow z materialu o modelach (jak Maria odtworzy wiedze?)
