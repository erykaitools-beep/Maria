# 2026-03-08 - Web Content Fetcher (zbudowany, nie podlaczony)

## Kontekst
Maria skonczy uczyc sie 7 plikow z `input/` w ciagu kilku godzin. Potem planner
bedzie dawal NOOP (brak materialu). Eryk zdecydowal: budujemy modul do pobierania
materialow z internetu, ale NIE podlaczamy go do plannera. Maria moze dzialac
2 dni bez zmian, a modul czeka gotowy do aktywacji.

## Co zbudowano

### agent_core/web_source/ (6 plikow + testy)
- `fetch_registry.py` - JSONL dedup (MERGE semantics, jak knowledge_index)
- `wiki_client.py` - Wikipedia PL API (opensearch + query+extracts)
- `rss_client.py` - RSS/Atom reader (stdlib xml.etree, zero nowych deps)
- `content_writer.py` - zapis do input/ jako web_{wiki|rss}_{slug}.txt
- `topic_suggester.py` - wybor tematow z KnowledgeAnalyzer (EXPAND + EXPLORE)
- `__init__.py` - `run_fetch_session()` jedyny entry point

### Testy
- 47 testow w `test_web_source.py` (all mocked HTTP)
- Testy: 1074 -> 1121

## Kluczowe decyzje
- **Zero nowych dependencies** - requests (juz mamy) + xml.etree (stdlib)
- **Zero LLM** w TopicSuggester - deterministyczny, oparty na KnowledgeAnalyzer
- **EXPAND vs EXPLORE** - Maria poszerza znane tematy I odkrywa nowe
- **Rate limiting** - 1 req/2s (Wiki), 1 req/1s (RSS) - grzeczne crawlowanie
- **Max 3-5 artykulow per sesja** - nie zalewamy input/
- **Istniejacy pipeline sam to znajdzie** - pliki w input/ sa automatycznie wykrywane

## Aktywacja (2 kroki)
Gdy Eryk zdecyduje ze czas podlaczyc:
1. `agent_core/planner/planner_model.py` -> `FETCH = "fetch"` w ActionType enum
2. `agent_core/planner/action_executor.py` -> `_exec_fetch()` wywolujacy `run_fetch_session()`

Komentarz w planner_model.py juz wskazuje gdzie dodac.

## Dokumentacja zaktualizowana
- CLAUDE.md: historia, testy, struktura, sekcja Web Source, nastepne kroki
- DEVELOPMENT_PLAN.md: status Warstwy 4, opis modulu, 2 kroki aktywacji
- ARCHITECTURE.md: web_source/ w drzewie agent_core, wersja 0.6
- planner_model.py: komentarz `# Future: FETCH = "fetch"`

## Na przyszlosc
- Mozna dodac wiecej feedow RSS (np. naukowe.pl, PAP nauka)
- TopicSuggester mozna rozbudowac o strategiy "FILL_GAPS" (tematy slabo zdane)
- ContentWriter mozna rozbudowac o wiecej source_type (np. "arxiv", "book")
- Rate limiting powinien byc konfigurowalny (teraz hardcoded)
