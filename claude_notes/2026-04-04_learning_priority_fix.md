# 2026-04-04 Learning Priority Fix + Expert Dedup

## Sesja z Erykiem

### Problemy znalezione:

1. **K11 Experiment dedup** - 3 identyczne propozycje (planner.ROUTINE_INTERVAL_TICKS 60->50).
   ProposalEngine nie sprawdza czy identyczna draft juz istnieje. Eryk zatwierdzil jedna, odrzucil reszta.
   TODO: dodac dedup w ProposalEngine.

2. **K7 blokuje critique** - 1948 consecutive failures!
   `critique` nie bylo w DEFAULT_ACTION_CLASSIFICATIONS, defaultowalo do RESTRICTED.
   Fix: dodane jako GUARDED (READ-ONLY, jak creative i self_analyze).

3. **Brak priorytetyzacji slabych tematow** - Maria wolala fetchowac nowe materialy
   zamiast uzupelniac luki (logika formalna 13% confidence, 15 prob egzaminu).

   Root cause: TeacherAgent P1-P6 i Planner _decide_learning_action() nigdy nie
   sprawdzaly belief confidence. Slabe tematy trafialy dopiero do P5 (hard_topic
   z gate completed>=3) albo P6 (ask_expert).

   Fix: P2.5 - miedzy exam (P2) a new files (P3):
   - Planner: _find_weak_topic_file() sprawdza world_model gaps < 0.3
   - TeacherAgent: hard_topic przeniesione z P5 do P2.5, bez gate

4. **Expert dedup bug** - Codex pytany 1137x o logike formalna!
   ExpertBridge nie sprawdzal czy material juz istnieje.
   _save_expert_response() appendowal zamiast sprawdzac rozmiar.
   expert_logika_formalna.txt mial 260k linii.

   Fix:
   - ExpertBridge: Step 0 - sprawdz czy input/expert_{topic}.txt > 5KB
   - ActionExecutor: skip save jesli > 5KB, "w" zamiast "a"
   - Cleanup: przyciete 4 bloated pliki do ostatniej odpowiedzi

### Obserwacje:
- Maria autonomicznie uzywa Codex (277 wywolan, 10/h limit)
- Self-analysis (NIM) poprawnie identyfikuje problemy (critique 0%, learn 0%)
- 98 beliefs z confidence < 0.3 (51 entities) - duzo do uzupelnienia
- 2 pliki hard_topic: expert_genetyka.txt (14 prob), expert_logika_formalna.txt (15 prob)

### Testy: 2769 passing (bez zmian)
