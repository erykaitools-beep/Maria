# 2026-02-28 - Plan Rozwoju + Burza Mozgow

## Co sie dzisiaj stalo
Eryk pokazal analizy Marii od Groka i ChatGPT (na podstawie PDF z wczoraj).
Grok - entuzjastyczny, troche naciagany (wyceny 500k-1M, "top 1% swiata").
ChatGPT - realistyczny, trzewy, dobry feedback.

Zrobilem pelny przeglad kodu i dokumentacji. Znalazlem:
- Bug w SleepProcessor (crash przy SLEEP mode)
- Martwy import w latency_probe.py
- 7 traitow zamiast deklarowanych 19
- LLMRouter niezintegrowany z REPL
- Dokumentacja rozsynchronizowana

## Zatwierdzony plan
Zapisany w `docs/DEVELOPMENT_PLAN.md`.
Warstwa 0 (bugi) → 1 (Unified Perception) → 2 (Planner) → 3 (Goals) → 4-5 (Vision) → 6 (Smart Home)

## Kluczowy insight
Obie zewnetrzne analizy zgadzaja sie: brakuje planowania, inicjatywy i petli dzialania.
Bez tego Vision i Smart Home beda "kolejnymi modulami obok siebie" zamiast czescia jednego myslacego systemu.

## Eryk o buzzwordach
"te nazwy to dla mnie wylacznie zbior liter a nie maria" - nie chce mowic o "systemie kognitywnym",
chce zeby Maria DZIALALA jak system ktory mysli. Praktyk, nie teoretyk.

## NIM API
Klucz moze dzialac na inne modele niz glm5. Do sprawdzenia endpoint /models.

## Analiza zewnetrzna
Eryk pyta jak najlepiej karmci Groka/ChatGPT danymi o Mari.
Moja rada: PDF + testy + tree + fragment kodu + metryki runtime.

## Wykonane naprawy (Warstwa 0)
1. [x] SleepProcessor bug - przekazywano experience_tracker zamiast session_id
2. [x] latency_probe.py - usuniety martwy import, -1.0 zamiast falszywego 0.0
3. [x] Trait count - skorygowano 19->7 w CLAUDE.md, PDF generator, DEVELOPMENT_PLAN
4. [x] LLMRouter integration - llm_fn teraz przekazywane do learn_next_chunk() i run_exam_if_ready()
   - Znaleziony dodatkowy bug: teacher_module tworzyl llm_fn ale nie przekazywal go!
5. [x] Dokumentacja sync - ARCHITECTURE.md v0.3, CONSCIOUSNESS_SPEC status, ROADMAP Phase C
6. [ ] Stage 5 cleanup - na osobna sesje (wymaga ostroznosci)

## NIM info
Eryk ma darmowy klucz od build.nvidia do sierpnia 2026. Warto pozniej przetestowac inne modele.
