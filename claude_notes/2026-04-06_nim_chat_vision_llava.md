# Sesja 2026-04-06: NIM Chat + Vision LLaVA + Voice Spec

## Co zrobiono

### NIM Chat w Web UI
- `LLMRouter.think()` teraz routuje przez NIM API gdy `NIM_CHAT_ENABLED=true`
- Grounded queries (vision, status, errors) ZAWSZE ida przez Ollama (tam jest kamera)
- `_is_grounded_query()` sprawdza OperationalQueryRouter przed routingiem
- Maria gada wyraznie lepiej po polsku (70B vs 8B)

### Vision LLaVA - Maria naprawde widzi!
- Problem: Web UI (maria-ui) i daemon (maria.service) to osobne procesy
- Daemon trzyma kamere, Web UI nie ma live cortex
- Fix: `_describe_frame_via_llava()` - czyta `meta_data/vision_frame.jpg` (zapisywany przez daemon co tick)
  i wysyla do LLaVA via Ollama API
- LLaVA poprawnie rozpoznala kostki Rubika na parapecie!
- Timeout: 120s (cold start LLaVA moze trwac 60-90s)

### Naprawione bugi
1. `import os` brakujacy w `maria_ui/app.py` - router NIM sie nie ladowal
2. `self._project_root` zamiast `self._root` w evidence_collector - JSON fallback nie dzialal
3. Oba bugi cicho polykane przez `except: pass` - trudne do debugowania

### Voice Spec
- `docs/VOICE_SPEC.md` - pelna specyfikacja modulu glosu
- Piper TTS (gosia-medium, 300MB, 20ms) + faster-whisper STT (small INT8, 2GB)
- 4 fazy implementacji
- Eryk poprosi Marii o zrobienie tego - Maria na NIM napisala plan (ogolnikowy)

## Stan po sesji
- NIM_CHAT_ENABLED=true w .env (aktywne)
- LLaVA pulled i dziala (4.5GB, ~40-50s na opis sceny)
- 27 testow router, 22 testow evidence_collector - all passing
- Commit: e8bdef0

## Na nastepna sesje
- Maria mowi "kubek w ksztalcie kostki Rubika" zamiast "kostka Rubika" - LLaVA 7B nie jest idealna
- Mozliwe upgrade: llava:13b (lepsza dokladnosc, wiecej RAM)
- Voice Phase 1 (TTS) mozna zaczac
- systemd migration: run_maria.py -> maria.py (V3 launcher)
- Vision wiring do homeostasis tick (REPL /vision, Web UI /vision page)

## Wazne techniczne
- LLaVA cold start: 60-90s! Pierwszy "co widzisz" po restarcie bedzie wolny
- Prompt po angielsku lepszy niz po polsku dla LLaVA (model jest angielski)
- Maria tlumaczy angielski opis LLaVA na polski w grounded_think()
- `vision_frame.jpg` musi byc < 60s stary (freshness check)
