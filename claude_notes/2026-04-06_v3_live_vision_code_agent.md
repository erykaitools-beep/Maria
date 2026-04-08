# Session 2026-04-06: V3 Live + Vision + Code Agent

## Co zrobilem

### 1. V3 Runtime Migration
- maria.py jako jedyny entry point (daemon + Web UI w jednym procesie)
- scripts/maria.service -> maria.py (zamiast run_maria.py)
- scripts/maria-ui.service -> OBSOLETE (Web UI w tym samym procesie)
- Deploy: sudo systemctl restart maria - dziala produkcyjnie

### 2. Vision Wiring
- 4 event types w perception/event.py (vision_percept, vision_motion, vision_alert, vision_health)
- VisionCortex.describe_scene_llava() - on-demand snap z LLaVA (~30s)
- EvidenceCollector.collect_vision() - LLaVA on-demand zamiast stats-only
- maria_ui/app.py: set_vision_cortex() - shared miedzy daemon i Web UI
- maria.py: share vision cortex po init modulow
- Kamera dziala: Innomaker USB 640x480@30fps, LLaVA pulled
- Problem: Maria halucynowala "czarny ekran" -> fix: LLaVA nie byl podpiety do SceneModule w tick (celowo), ale tez nie byl dostepny dla chatu (brak wiring vision_cortex w Web UI evidence collector)

### 3. Code Agent (Faza 1-4 COMPLETE)
- agent_core/code_agent/ - 5 plikow:
  - models.py: PlannedFile, GeneratedFile, WrittenFile, TestResult, ApprovalCheckpoint
  - session.py: CodeSession lifecycle + JSONL persist + CodeSessionStore
  - prompt_builder.py: architecture context + prompt templates (design/generate/fix/review)
  - agent.py: CodeAgent orchestrator (plan->generate->write->test->fix->review)
  - __init__.py: exports
- agent_core/modules/code_module.py - REPL /code
- TaskDecomposer: CODE category + _CODE_KEYWORDS + _steps_code()
- ExecutionPlan: code_design/generate/write/test/fix/review estimates
- SharedContext: code_agent field
- Homeostasis wiring: CodeAgent init z OpenClaw + Claude/Codex + Telegram
- main.py: register CodeModule

### 4. Telegram Improvements
- /code -> Code Agent (nowy, autonomiczne kodowanie)
- /codex -> stary Codex/ChatGPT analysis (przeniesiony z /code)
- /help -> pogrupowany po kategoriach (System, Cele, Wiedza, Kodowanie, AI, Diagnostyka)

## Kluczowe decyzje
- Code Agent uzywa Claude (3/h) do designu i zlozonego kodu, Codex (10/h) do prostszych plikow
- 2 mandatory approval gates: po planie + po generacji kodu
- Self-modify guard: zapis do agent_core/ wymaga dodatkowego approval
- Session persist do JSONL: WAITING_BUDGET -> resume po odnowieniu limitow
- Max 3 iteracje fix loop

## Testy
- 54 nowych testow code agent
- 3371 total, 0 failures

## Nastepne kroki
- Test /code na Telegramie (pierwszy prawdziwy task)
- Faza 5 (przyszlosc): git integration, workspace isolation, self-modification protocol
- Eryk chce open source na GitHub po tym jak Code Agent bedzie przetestowany
- Uwaga: Eryk widzi V3 jako "Maria wyglada jak AGI z zewnatrz" - Code Agent to ostatni brakujacy element

## Nastepna sesja: Self-Healing + proaktywne alerty

Eryk chce zeby Maria umiala:
1. Wykryc ze jest w NOOP loop / zapetleniu i powiedziec o tym na Telegram
   - "Utknelam w NOOP od 2h, oto co widze w logach, probowalme X"
2. Sama sprobowac zdiagnozowac problem (rozszerzenie K12 Self-Analysis)
3. Sprobowac naprawic (restart modulu, zmiana parametru)
4. Jesli nie moze - poprosic operatora z kontekstem co probowalme

Kierunek: Maria przechodzi od "informuje o problemie" do "diagnozuje i probuje naprawic, a jak nie moze to prosi o pomoc z kontekstem".

Pliki do rozszerzenia:
- agent_core/self_analysis/ - diagnostyka problemow
- agent_core/telegram/ - proaktywne alerty z kontekstem
- agent_core/planner/ - NOOP loop detection -> self-heal trigger

## Notatki o Eryku
- Wizja V3: jeden plik, onboarding, samowiedza, kodowanie, koszty, raporty, "AGI z zewnatrz"
- "idziemy po koleji" - lubi plan i systematyczne wykonanie
- Cieszy sie z postepow ("pisze do Mari i zobaczymy :)")
- Kamera patrzy za okno na parapet z kostka Rubika
