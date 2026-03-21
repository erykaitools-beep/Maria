# 2026-03-18: OOM Crash Fix - intelligent_chunk_text()

## Problem
Maria restartowala sie co 2-3 minuty, 473+ restartow systemd. Pamiec rosla do 100% i OOM killer zabijal proces (SIGKILL).

## Diagnoza (dlugie sledztwo)
1. Poczatkowo podejrzewalem OllamaBrain.history (unbounded list) - naprawione deque(maxlen=50), ale NIE to byl root cause
2. Sprawdzilem num_ctx (KV cache Ollama) - dodano 4096, ale Ollama nie byl winny
3. Eliminacja po kolei: NIM client, LLMRouter, tick loop, metadata - wszystko czyste
4. Binary search izolacji: nawet z fake LLM (bez sieci!) pamiec rosla ~930MB/s
5. **Root cause:** `intelligent_chunk_text()` w `maria_core/learning/learning_agent.py`

## Root Cause (szczegoly)
Plik `input_007_meta_system_poznawczy.txt` ma 2616 znakow > MAX_CHUNK_SIZE (2000).
Funkcja wchodzi w while loop. Na koncu tekstu:
- `start=2466`, `end=2616` (==len(text))
- Chunk dodany
- `start = end - CHUNK_OVERLAP = 2616 - 150 = 2466` -- TEN SAM START!
- Safety check `if start >= end` nie lapie bo `2466 < 2616`
- Nieskonczona petla tworzaca identyczne chunki az do OOM

## Fix
1. Sledzenie `prev_start` - jesli `start <= prev_start` po overlap, wymuszamy postep o MIN_CHUNK_SIZE
2. Hard limit 100 chunkow jako bezpiecznik
3. Dodatkowe hardening: deque w OllamaBrain, num_ctx=4096, observer._read_jsonl() bounded

## Commit
`cffadc5` - fix: OOM crash - infinite loop in intelligent_chunk_text() + memory hardening

## Lekcje
- OOM w Pythonie jest trudny do debugowania bo proces jest killowany z zewnatrz (signal 9)
- Binary search izolacji (wylaczanie modulow po kolei) jest najskuteczniejsza metoda
- Fake LLM (zwracajacy staly string) to swietne narzedzie do izolacji problemow I/O vs CPU/memory
- Overlap w chunkingu to klasyczny zrodlo nieskonczonej petli - zawsze sprawdzac postep

## Stan po naprawie
- 1194 testow passing
- Maria uruchomiona, dziala stabilnie
- Commit zawiera tez: ActionType.FETCH activation, web_source wiring, meta_data updates

## Inne zmiany w tej sesji (nie moje, juz byly na branchu)
- K6 World Model (agent_core/world_model/) - 69 testow, zaimplementowany przed ta sesja
- Web Fetcher aktywowany w planner (ActionType.FETCH + _exec_fetch())
- observer._read_jsonl() bounded do 10k lines (OOM prevention)
- audit_log zmieniony na deque (w core.py, juz bylo przed ta sesja)
