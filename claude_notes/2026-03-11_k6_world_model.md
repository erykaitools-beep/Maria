# 2026-03-11 - K6 World Model / Belief System

## Kontekst
Sesja z Erykiem. Najpierw sprawdzilismy stan Marii (daemon dzialal, Maria w ACTIVE).
Poprzednia sesja (2026-03-08) naprawila 4 bugi + Bug 5 (SLEEP forever) + NIM timeout +
retention rate. Dzis przeszlismy prosto do K6.

## Sesja 1/2 (poprzedni context window)
- Bug 5 fix: `record_activity()` w `_finalize_plan()` - Maria nie tkwi w SLEEP po akcji
- NIM timeout: 120s -> 45s, timeout retries 3 -> 1 (fail fast, fallback Ollama)
- Retention rate: observer sprawdza tez `score >= 0.7` gdy brak `passed` field
- Commit: `1579366`

## K6 World Model (ten context window)
Implementacja kompletna, commit `2448990`.

### Nowe pliki (agent_core/world_model/)
1. **belief_model.py** - Frozen Belief dataclass
   - EntityType: TOPIC, FILE, CONCEPT, MODULE, PERSON, PLACE
   - BeliefType: FACT (verified by exam), OBSERVATION (learned), HYPOTHESIS (inferred)
   - BeliefSource: LEARNING, EXAM, MEMORY_FACT, SYSTEM, USER
   - create_belief() factory, to_dict/from_dict serialization

2. **belief_store.py** - JSONL persistence
   - MERGE semantics (last per belief_id wins) - ten sam pattern co knowledge_index
   - Indexes: by_entity, by_entity_type, by_tag
   - revise(): tworzy nowa wersje, stara dostaje superseded_by
   - MAX_CURRENT_BELIEFS = 2000 cap z pruning najslabszych
   - Append-only save (jak GoalStore)

3. **belief_builder.py** - Populuje beliefs z istniejacych JSONL
   - build_topic_beliefs(): z longterm_memory tags, confidence = occurrences/5
   - build_file_beliefs(): ze statusow w knowledge_index
   - build_concept_beliefs(): z key_points, +0.2 jesli egzamin zdany
   - update_from_exam(): pass +0.1 + FACT, fail -0.15
   - _normalize_tag(): lowercase, strip, filter stop words, 2-30 chars
   - Idempotent (find_by_entity_and_source dedup)

4. **query.py** - API dla Plannera
   - get_topic_confidence_map() - avg confidence per topic
   - get_knowledge_gaps() - sorted by lowest confidence
   - get_facts_for_topic() - tylko FACT beliefs
   - get_entity_summary() - wszystko o jednej entity
   - get_world_summary() - kompaktowe podsumowanie

5. **__init__.py** - WorldModel facade
   - load() / build() / process_exam_result() / save()
   - Domyslne sciezki: meta_data/beliefs.jsonl + memory/*.jsonl

### Integracja
- **shared_context.py**: nowe pole `world_model`
- **homeostasis_module.py**: wiring blok (load existing lub build od zera)
- **planner_core.py**:
  - `_gather_context()` -> world_summary + knowledge_gaps[:5]
  - `_finalize_plan()` -> revise beliefs po exam
  - `_auto_create_learning_goal()` -> min confidence topic z K6 (fallback na max unfinished)
- **goal_selector.py**: opcjonalny world_summary param

### Testy
- 69 nowych w test_world_model.py
- 1194 total passing (1125 + 69)

## Kluczowe decyzje
- **Frozen dataclass** jak PerceptionEvent - immutable beliefs, nowe wersje przez revise()
- **MERGE semantics** jak knowledge_index - append-only JSONL, last record per ID wins
- **Zero LLM** w calym module - deterministyczny, rule-based (ADR-013)
- **BeliefBuilder READ-ONLY** wobec sources - czyta istniejace JSONL, nie modyfikuje ich
- **Cap 2000** beliefs - pruning najslabszych confidence gdy przekroczy
- **Backward compatible** - world_model=None nie psuje nic

## Obserwacje
- Maria na produkcji wciaz uczy sie z 7 plikow w input/
- Web Content Fetcher gotowy ale nie podlaczony - to moze byc nastepny krok
- K6 dziala od razu na istniejacych danych (build_all z 3 JSONL sources)
- Eryk preferuje krok po kroku, nie skakac - wiec K7 dopiero po stabilizacji K6

## Nastepne kroki (propozycja)
1. **Aktywacja Web Fetchera** (2 kroki) - Maria potrzebuje nowych materialow
2. **REPL/Web UI dla K6** - `/beliefs`, `/beliefs gaps`, panel w Web UI
3. **Multi-day test** K6 na produkcji - czy belief revision dziala poprawnie
4. **K7 Autonomy Policy** - gdy praktyka pokaze ze PlannerGuard nie wystarczy
5. **Stabilizacja** - analiza planner_decisions.jsonl z K6 context

## Stan projektu
- Branch: refactor/homeostasis
- Testy: 1194 passing
- Commits: ...1579366 (bugfixes) -> 2448990 (K6)
- K1-K6: DONE
- K7-K10: docelowe, przyrostowo
