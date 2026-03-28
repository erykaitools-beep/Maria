# 2026-03-28 - Memory Hierarchy Analysis (Phase 2 prep)

## Wynik analizy

34 zrodla danych w Marii. Podzielone na 15 tierow.

### Primary Sources of Truth (CANONICAL)
1. `memory/knowledge_index.jsonl` (66KB) - status plikow, exam scores
2. `memory/exam_results.jsonl` (863KB) - szczegolowe wyniki egzaminow
3. `meta_data/homeostasis_events.jsonl` (1.8MB) - stan systemu co tick

### Derived Data (generowane z primary)
- `beliefs.jsonl` (53KB) <- z knowledge_index + longterm_memory
- `evaluation_reports.jsonl` (363KB) <- z knowledge_index + exam_results + homeostasis
- `self_analysis_reports.jsonl` (49KB) <- z evaluation_reports + knowledge_index

### Legacy/Stale (do wyrzucenia/naprawienia)
- `conversation_history.jsonl` (1.1KB, 2 wpisy) - MARTWE
- `conversation_summaries.jsonl` (396B, 1 wpis) - MARTWE
- `trauma_events.jsonl` (0B) - LEGACY, nigdy uzyte
- `rewards_log.jsonl` (2B) - LEGACY
- `decisions_log.jsonl` (4.3KB) - SUPERSEDED by planner_decisions

## 5 problemow staleness

### A: Semantic Vectors nie kasuja sie
semantic_vectors.jsonl (2.8MB, 10k cap) - gdy plik znika z input/,
wektory zostaja. TopicSuggester moze sugerowac usuniete tematy.
FIX: dodac deletion tracking w indexer.py

### B: Conversation History martwa
Tylko 2 wpisy z 27 lutego. ConversationMemory nie zapisuje.
K13 memory_retriever.py probuje czytac - dostaje stary kontekst.
FIX: albo reaktywowac zapis, albo usunac czytnik

### C: Beliefs moga byc stale
belief_builder.py generuje z knowledge_index, ale nie jest hookowany
w promotion flow. Beliefs moga nie odzwierciedlac najnowszych egzaminow.
FIX: hookuj belief_builder w sandbox.promote()

### D: Topic Hints bez walidacji
topic_hints.jsonl wskazuje na pliki, ale nie sprawdza czy plik istnieje.
FIX: walidacja w TopicSuggester

### E: Identity vs Session
consciousness_identity.json trackuje session_count oddzielnie od homeostasis ticks.
Po crash moze byc niespojne.
FIX: sync identity.session_count z tick_count

## Nastepne kroki Phase 2

1. Naprawic staleness A, C, D (konkretne, praktyczne)
2. Unified MemoryQuery API - jeden interface zamiast 5 oddzielnych JSONL
3. Freshness metadata - `last_synced_ts` na derived stores
4. Truth hierarchy document (ADR-023)

## Uwaga
Phase 2 to duza praca - pewnie kilka sesji. Nie robic wszystkiego naraz.
