# Sesja 2026-03-27 - Semantic Memory + Priority Escalation + CDL

## Wykonane (duzo!)

### 1. Meta-goal Priority Escalation
- Tension streak tracking w CreativeStore (creative_tension_streaks.jsonl)
- Priority boost w ReflectionWorkspace: streak * 0.05, max +0.2
- PROPOSED displacement w GoalStore: wyzszy priorytet wypycha nizszy
- Telegram /priority <id> <0-1> - operator recznie zmienia priorytet
- /goals ulepszone: ID prefix, priorytet, stats
- 23 testy

### 2. Semantic Memory (nomic-embed-text)
- agent_core/semantic/ - 3 pliki (embedding_model, vector_store, __init__)
- nomic-embed-text pulled na mini PC (274MB, 768-dim)
- MODEL-05 w registry zaktualizowany
- VectorStore: in-memory + JSONL persist, namespaces, cosine search, cap 10k
- Auto-indexer: 157 knowledge + 95 beliefs + 23 hints = 275 vectors
- Startup delay 60s (fix REDUCED mode po restarcie)
- Incremental indexing po fetch actions
- TopicSuggester: semantic reranking (novelty scoring)
- MemoryRetriever: embedding search z keyword fallback
- 57 testow

### 3. Conversation-Driven Learning
- learning_intent.py: 15 PL + 4 EN regex patterns (zero LLM)
- conversation_learning.py: process_user_message() bridge
- REPL: intent detection przed brain.think()
- Telegram /learn <temat> command
- LEARNING goal tworzony jako PENDING (user explicitly asked = skip PROPOSED)
- Planner: conversation goals always feasible, NOOP -> FETCH if no files
- GoalSelector: source=conversation bypasses file check
- 28 testow

### 4. Bugfixy i maintenance
- 3 pre-existing test failures naprawione (72h timeout, MODEL-07, ASK_EXPERT)
- 2 telegram test env issues naprawione (patch.dict os.environ)
- Planner __new__ tests fixed (missing _world_model, _expert_fn, _knowledge_analyzer)
- CLAUDE.md zaktualizowany
- ADR-021 dodany (embeddings zamiast keyword retrieval)

## Statystyki sesji
- Start: 1985 testow
- Koniec: 2151 testow (+166 nowych)
- 4 commity
- ~3000 linii nowego kodu
- Zero regressions

## Obserwacje
- Maria wpada w REDUCED po kazdym restarcie z powodu CPU spike (creative + learning)
  - Fix: startup delay 60s na embedding indexer
  - REDUCED trwa 2-5 min, wraca sama do ACTIVE
- print() w homeostasis_module nie widac w journalctl (daemon mode)
  - Zmienione na logger.info/warning
- WebUI ma osobny OllamaBrain bez SharedContext - CDL tam nie dziala
  - Na przyszlosc: wspolny SharedContext miedzy daemon a WebUI
- ctx.config.BASE_DIR nie istnieje w SharedContext
  - Fix: from maria_core.sys.config import BASE_DIR

## Nastepne kroki
- Multi-Source Learning (cross-LLM validation) - od zera
- WebUI: Semantic Memory stats w /status panel
- WebUI: CDL integration (wymaga shared context)
- Eryk testuje /learn na Telegramie -> obserwowac logi
- Rozwazyc: periodic re-indexing (beliefs/hints zmieniaja sie w runtime)
