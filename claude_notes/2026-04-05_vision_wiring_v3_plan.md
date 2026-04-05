# Sesja 2026-04-05 - Vision Wiring + V3 Plan

## Co zrobiono

### Vision Wiring (kompletne)
- SharedContext.vision_cortex
- HomeostasisCore Phase 8.5: VisionCortex.perceive() co tick
- VisionPerceptionAdapter -> K1 PerceptionEvents -> PerceptionBuffer
- homeostasis_module.py: init z USBWebcamSensor (flip=True), MotionModule, SceneModule
- LLaVA function stored on SceneModule for on-demand use (nie w tick - za wolne)
- REPL /vision: 7 subcommands (status, snap, health, motion, scene, open, close)
- Web UI /vision: live preview (1fps JS refresh), 3 tabs, 5 API endpoints
- Status page: Vision panel z thumbnail, health bar, quality, summary
- vision_state.json + vision_frame.jpg pisane przez tick loop
- Grounding pipeline: GROUNDED_VISION w QueryRouter, collect_vision(), _build_vision()
- System prompt: "Masz oko (kamere USB)"
- Vision-specific format prompt dla LLM ("Mow w pierwszej osobie: Widze...")

### LLaVA
- ollama pull llava (4.7GB) - sciagnieta
- Za ciezka na concurrent local use (llama3.1:8b + llava = OOM/timeout)
- Zostawiona jako on-demand w /vision snap (nie w tick)
- Tick overrun 31s kiedy llava byla w tick loop - naprawione

### Bug fixes
- deque slice bug w trim_brain_history() (TypeError: sequence index must be integer, not 'slice')
- Vision interval zmniejszony z 5 na 1 tick
- MJPEG stream nie dzialal z Werkzeug - zamieniony na JS polling co 1s

### V3 Planning
- Otrzymano V3 Definition od ChatGPT (docs/plans/maria_v2_roadmap.docx)
- V2 gates: Maria juz spelnia 7/7 wymagan V2
- Otrzymano V3 Technical Roadmap od ChatGPT (15 modulow, 5 faz)
- Zapisano jako docs/plans/V3_TECHNICAL_ROADMAP.md
- Zero kolizji architektonicznych z V2
- Nowa warstwa: agent_core/orchestrator/

## Obserwacje

### Sprzet
- Innomaker U20CAM: fixed focus (brak autofocusu), trzeba recznie ustawic pierscien
- LLaVA + llama3.1:8b jednoczesnie to za duzo na 32GB RAM
- SceneModule w tick daje stats-based opis (jasnosc, kolory, zlozonosc) - nie opis sceny

### LLM i vision
- llama3.1:8b halucynuje opisy scen jesli nie ma twardych danych
- Grounding pipeline kluczowy - bez niego LLM mowi "nie mam kamery"
- ResponseBuilder musi miec handler dla kazdego ResponseMode (inaczej fallback na status)

### V3 assessment
- V3 to glownie warstwa produktowa na V2
- Zasada: wrap, adapt, expose, orchestrate - NIE rewrite
- Najwieksze luki: unified entry, task orchestration, cost/time estimation
- Operator visibility (~90%) i memory continuity (~85%) juz silne

## Nastepne kroki
- V3 Phase A: UnifiedLauncher + OnboardingFlow + UserFacingSelfModel
- Ewentualnie: zewnetrzne API do opisu scen (NIM multimodal? Claude Vision?)
