# M.A.R.I.A. - Specyfikacja Modulu Glosu (Usta + Uszy)

> **Data utworzenia:** 2026-04-06
> **Status:** Specyfikacja do implementacji
> **Filozofia:** Glos jako organ - Maria mowi i slucha, nie "odtwarza audio"
> **Podejscie:** Offline-first, graceful degradation, przyrostowa implementacja

---

## 1. Zasada nadrzedna: Biologiczna inspiracja

### Ludzki glos vs. syntezator

| Aspekt | Syntezator klasyczny | Ludzki glos | M.A.R.I.A. Voice |
|--------|---------------------|-------------|-------------------|
| Awaria | 0 lub 1 | Chrypka, szept | Graceful degradation |
| Emocje | Brak | Ton, tempo, akcent | Personality-aware TTS |
| Sluch | Brak | Selektywny (koktajl party) | VAD + Whisper |
| Adaptacja | Brak | Glosniej w halasie | Dynamiczne parametry |
| Pamiec | Brak | Rozpoznaje glosy | Speaker ID (future) |

### Graceful Degradation - glos

```
FULL VOICE (100%)
    |
    v obciazenie CPU
SLOWER VOICE (80%) - dluzszy czas odpowiedzi TTS
    |
    v brak modelu TTS
TEXT ONLY (60%) - tylko tekst, bez audio
    |
    v brak modelu STT
ONE-WAY VOICE (40%) - Maria mowi, ale nie slyszy
    |
    v brak mikrofonu/glosnika
SILENT MODE (0%) - tylko tekst (jak teraz)
```

Maria NIGDY nie mowi "modul glosu nie dziala" - mowi "mam chrypke" lub "slabo slyszam".

---

## 2. Architektura warstwowa

```
+-------------------------------------------------------------+
|                    MARIA CONSCIOUSNESS                       |
|              (Unified Perception - jedno "ja")               |
+-------------------------------------------------------------+
|                    VOICE CORTEX                              |
|     Koordynacja mowy i sluchu, kolejkowanie                 |
|     Personality-aware parametry TTS                          |
+---------------------------+---------------------------------+
|      MOUTH (TTS)          |         EAR (STT)              |
|  Piper gosia-medium       |   faster-whisper small         |
|  PCM streaming            |   Silero VAD + transcription   |
+---------------------------+---------------------------------+
|                  AUDIO I/O LAYER                             |
|  Web UI: WebSocket + Web Audio API                          |
|  Telegram: OGG Opus + FFmpeg                                |
|  Local: ALSA/PulseAudio (optional)                          |
+-------------------------------------------------------------+
```

---

## 3. Stos technologiczny

### 3.1 TTS - Piper (Usta)

| Parametr | Wartosc |
|----------|---------|
| **Silnik** | Piper TTS (ONNX, offline) |
| **Glos** | `pl_PL-gosia-medium` (zenski, polski) |
| **Format** | 22050 Hz, 16-bit PCM mono |
| **Latencja** | 20-30ms na CPU (Ryzen 5) |
| **RAM** | ~300 MB |
| **Dysk** | ~80 MB (model .onnx + .json) |
| **Streaming** | `synthesize_stream_raw()` - chunked PCM |
| **Pip** | `piper-tts` |

**Dlaczego Piper a nie Coqui:**
- Coqui: ~5GB RAM, sekundy latencji na CPU, firma zamknieta
- Piper: ~300MB RAM, 20ms latencji, aktywnie rozwijany
- Piper ma 4 polskie glosy (gosia = naturalny zenski)

### 3.2 STT - faster-whisper (Uszy)

| Parametr | Wartosc |
|----------|---------|
| **Silnik** | faster-whisper (CTranslate2) |
| **Model** | `small` (INT8 quantized) |
| **Jezyk** | Polish (`pl`) |
| **WER** | ~10% (akceptowalne dla konwersacji) |
| **RAM** | ~2 GB |
| **Dysk** | ~250 MB |
| **Latencja** | <1s dla 5s wypowiedzi |
| **Pip** | `faster-whisper` |

**Dlaczego `small` a nie `large-v3`:**
- large-v3: ~10GB RAM (za duzo obok Ollamy)
- small INT8: ~2GB RAM, 6x realtime, wystarczajaca dokladnosc
- Mozliwosc upgrade do `medium` (5GB) jesli potrzeba

### 3.3 VAD - Silero (Wykrywanie mowy)

| Parametr | Wartosc |
|----------|---------|
| **Silnik** | Silero VAD v6 |
| **Model** | ONNX (1-2 MB) |
| **Latencja** | <1ms na 30ms chunk |
| **CPU** | 0.43% (zaniedbywalny) |
| **Pip** | `silero-vad` |

**Rola:** Wykrywa poczatek/koniec mowy w strumieniu audio. Oszczedza CPU - Whisper transkrybuje tylko segmenty z mowa, nie cisze.

### 3.4 Budzet zasobow

| Zasob | Obecne uzycie | Voice module | Lacznie | Limit |
|-------|---------------|-------------|---------|-------|
| **RAM** | ~12 GB (Ollama) | ~2.3 GB | ~14.3 GB | 32 GB |
| **CPU** | Zmienny | <5% idle, peak na STT | OK | 6 cores |
| **Dysk** | ~6 GB modele | ~330 MB | ~6.3 GB | 1 TB |

---

## 4. Struktura plikow

```
agent_core/voice/
  __init__.py          # VoiceModule facade + run_voice_pipeline()
  voice_cortex.py      # Koordynacja TTS/STT, kolejkowanie, personality
  tts_engine.py        # PiperTTS wrapper (synthesize, stream, voice config)
  stt_engine.py        # WhisperSTT wrapper (transcribe, language detect)
  vad.py               # SileroVAD wrapper (detect speech segments)
  audio_io.py          # Format conversion (PCM, WAV, OGG), resampling
  voice_model.py       # VoiceEvent, VoiceState, VoiceConfig dataclasses
  voice_health.py      # Health monitoring (model loaded, latency, errors)

agent_core/tests/
  test_voice_tts.py
  test_voice_stt.py
  test_voice_vad.py
  test_voice_cortex.py
  test_voice_io.py
```

---

## 5. Interfejsy (API)

### 5.1 VoiceCortex - Glowna fasada

```python
class VoiceCortex:
    """Koordynacja mowy i sluchu."""

    def speak(self, text: str, emotion: str = "neutral") -> bytes:
        """
        Zamien tekst na mowe (PCM audio).

        Args:
            text: Tekst do wymowienia
            emotion: Emocja (neutral, happy, sad, excited) - wplywa na tempo/ton

        Returns:
            Raw PCM bytes (22050 Hz, 16-bit mono)
        """

    def speak_stream(self, text: str) -> Iterator[bytes]:
        """
        Streaming TTS - zwraca chunki audio w miare generowania.
        Dla Web UI WebSocket (niska latencja).
        """

    def listen(self, audio: bytes, sample_rate: int = 16000) -> str:
        """
        Zamien mowe na tekst.

        Args:
            audio: Raw PCM bytes
            sample_rate: Sample rate (default 16kHz)

        Returns:
            Transkrypcja tekstu
        """

    def listen_stream(self, audio_chunks: Iterator[bytes]) -> str:
        """
        Streaming STT z VAD - buforuje chunki, transkrybuje segmenty mowy.
        Dla Web UI WebSocket (real-time).
        """

    def get_health(self) -> VoiceHealth:
        """Stan zdrowia modulu glosu (TTS loaded, STT loaded, latency)."""

    def is_available(self) -> bool:
        """Czy modul glosu jest dostepny (przynajmniej TTS)."""
```

### 5.2 PiperTTS - Silnik mowy

```python
class PiperTTS:
    """Wrapper na Piper TTS."""

    def __init__(self, voice: str = "pl_PL-gosia-medium", data_dir: str = "models/piper/"):
        """
        Args:
            voice: Nazwa glsu Piper (z katalogu voices)
            data_dir: Katalog z modelami .onnx
        """

    def synthesize(self, text: str, speed: float = 1.0) -> bytes:
        """Caly tekst -> caly audio (PCM)."""

    def synthesize_stream(self, text: str, speed: float = 1.0) -> Iterator[bytes]:
        """Tekst -> chunki audio (streaming, niska latencja)."""

    def set_voice(self, voice: str) -> None:
        """Zmien glos (przeladuj model)."""

    def get_available_voices(self) -> List[str]:
        """Lista dostepnych glosow w data_dir."""
```

### 5.3 WhisperSTT - Silnik sluchu

```python
class WhisperSTT:
    """Wrapper na faster-whisper."""

    def __init__(self, model_size: str = "small", compute_type: str = "int8"):
        """
        Args:
            model_size: tiny/base/small/medium/large-v3
            compute_type: int8/float16/float32
        """

    def transcribe(self, audio: bytes, language: str = "pl") -> TranscriptionResult:
        """
        Transkrybuj audio.

        Returns:
            TranscriptionResult(text, language, confidence, segments)
        """

    def detect_language(self, audio: bytes) -> str:
        """Wykryj jezyk z pierwszych 30s audio."""
```

### 5.4 SileroVAD - Detekcja mowy

```python
class SileroVAD:
    """Voice Activity Detection."""

    def __init__(self, threshold: float = 0.5, min_speech_ms: int = 250):
        """
        Args:
            threshold: Prog decyzyjny (0.0-1.0)
            min_speech_ms: Minimalna dlugosc mowy (filtruje szumy)
        """

    def process_chunk(self, chunk: bytes) -> bool:
        """Czy chunk zawiera mowe? (True/False)"""

    def get_speech_segments(self, audio: bytes) -> List[Tuple[float, float]]:
        """Zwroc segmenty mowy [(start_s, end_s), ...]"""

    def reset(self) -> None:
        """Reset stanu (nowa sesja nasluchiwania)."""
```

---

## 6. Integracja z istniejacymi systemami

### 6.1 Web UI - WebSocket Audio

```
[Browser Mic]
     | getUserMedia({audio: true})
     | AudioWorklet: resample to 16kHz mono PCM
     v
[WebSocket 'voice_audio' event]
     | 30ms chunks
     v
[Server: SileroVAD]
     | speech detected?
     v
[Server: WhisperSTT]
     | text
     v
[Server: brain.think(text)]  <-- istniejacy pipeline
     | response text
     v
[Server: PiperTTS]
     | PCM audio chunks
     v
[WebSocket 'voice_response' event]
     | streaming audio
     v
[Browser: AudioContext.play()]
```

**Nowe SocketIO events:**

```python
# Client -> Server
@socketio.on('voice_start')      # Rozpocznij nasluchiwanie
@socketio.on('voice_audio')      # Chunk audio (PCM bytes)
@socketio.on('voice_stop')       # Zakoncz nasluchiwanie

# Server -> Client
socketio.emit('voice_transcript') # Transkrypcja w czasie rzeczywistym
socketio.emit('voice_response')   # Audio odpowiedzi (PCM chunks)
socketio.emit('voice_status')     # Stan (listening, thinking, speaking)
```

**Web UI zmiana:**
- Przycisk mikrofonu w chacie (obok pola tekstowego)
- Przycisk glosnika przy odpowiedziach Marii (odtworz glosem)
- Opcja "always speak" w ustawieniach (Maria mowi kazda odpowiedz)

### 6.2 Telegram - Voice Messages

```
[Telegram Voice Message .oga]
     | bot.get_file() + download
     v
[FFmpeg: OGA -> WAV 16kHz mono]
     v
[WhisperSTT.transcribe()]
     | text
     v
[brain.think(text)]  <-- istniejacy pipeline
     | response text
     v
[PiperTTS.synthesize()]
     | WAV audio
     v
[FFmpeg: WAV -> OGG Opus]
     v
[bot.send_voice(chat_id, ogg)]
```

**Nowy handler w `agent_core/telegram/`:**

```python
# telegram_bridge.py - nowy handler
def handle_voice_message(update):
    """Obsluga wiadomosci glosowych od operatora."""
    voice = update.message.voice
    file = bot.get_file(voice.file_id)
    # download -> convert -> transcribe -> think -> TTS -> send_voice
```

### 6.3 Homeostasis Integration

```python
# homeostasis_module.py - Phase 12: VOICE
if voice_cortex and voice_cortex.is_available():
    voice_health = voice_cortex.get_health()
    # Perception event: VOICE_HEALTH
    # Health contributes to overall system health
```

### 6.4 Consciousness Integration

```python
# Personality wplywa na parametry TTS
personality = consciousness.get_traits()
speed = 1.0 + (personality.get("curiosity", 0.5) - 0.5) * 0.2  # ciekawsza = szybsza
# Emocja z ExperienceTracker -> emotion parameter
emotion = experience_tracker.get_current_emotion()
audio = voice_cortex.speak(text, emotion=emotion)
```

### 6.5 K1 Perception - Nowe eventy

```python
# Nowe PerceptionSource i event types
class PerceptionSource(Enum):
    VOICE = "voice"           # Nowe

class VoiceEventType:
    SPEECH_DETECTED = "speech_detected"     # VAD wykryl mowe
    SPEECH_TRANSCRIBED = "speech_transcribed" # STT zakonczyl
    SPEECH_SYNTHESIZED = "speech_synthesized" # TTS zakonczyl
    VOICE_ERROR = "voice_error"              # Blad modulu
```

---

## 7. Konfiguracja

### 7.1 .env

```bash
# --- Voice Module ---
# Wlacz modul glosu (domyslnie false)
VOICE_ENABLED=false

# TTS: glos Piper (pl_PL-gosia-medium, pl_PL-darkman-medium)
VOICE_TTS_MODEL=pl_PL-gosia-medium

# STT: model Whisper (tiny/base/small/medium)
VOICE_STT_MODEL=small

# STT: typ obliczen (int8/float16)
VOICE_STT_COMPUTE=int8

# VAD: prog detekcji mowy (0.0-1.0)
VOICE_VAD_THRESHOLD=0.5

# Web UI: automatyczne odtwarzanie glosem (true/false)
VOICE_AUTO_SPEAK=false

# Telegram: odpowiadaj glosem na voice messages (true/false)
VOICE_TELEGRAM_REPLY=true
```

### 7.2 Model Registry (MODEL-07)

```python
# agent_core/llm/model_registry.py
MODEL_07 = ModelSpec(
    role=ModelRole.VOICE,
    name="piper-gosia",
    size_gb=0.08,
    ram_tier="S",       # <1GB
    startup="warm",     # ladowany na starcie jesli VOICE_ENABLED
    mutex=False,        # nie koliduje z innymi
    notes="Piper TTS pl_PL-gosia-medium, ONNX, CPU"
)

MODEL_08 = ModelSpec(
    role=ModelRole.HEARING,
    name="whisper-small-int8",
    size_gb=0.25,
    ram_tier="M",       # ~2GB w RAM
    startup="cold",     # ladowany on-demand (przy pierwszym voice input)
    mutex=False,
    notes="faster-whisper small INT8, CPU, Polish"
)
```

---

## 8. Plan implementacji (4 fazy)

### Faza 1: TTS - Maria mowi (MVP)
**Cel:** Maria potrafi zamieniac tekst na mowe

- [ ] `tts_engine.py` - PiperTTS wrapper
- [ ] `voice_model.py` - dataclasses (VoiceConfig, VoiceEvent, VoiceHealth)
- [ ] `audio_io.py` - PCM/WAV/OGG konwersja
- [ ] Download glsu `pl_PL-gosia-medium`
- [ ] Web UI: przycisk glosnika przy odpowiedziach
- [ ] Testy: 30+
- [ ] **Szacowany czas:** 1 sesja

### Faza 2: STT - Maria slucha
**Cel:** Maria rozumie mowe (transkrypcja)

- [ ] `stt_engine.py` - WhisperSTT wrapper
- [ ] `vad.py` - SileroVAD wrapper
- [ ] Web UI: przycisk mikrofonu + streaming audio
- [ ] WebSocket events (voice_start, voice_audio, voice_stop)
- [ ] Testy: 30+
- [ ] **Szacowany czas:** 1 sesja

### Faza 3: Voice Cortex - Pelna integracja
**Cel:** Koordynacja mowy/sluchu, integracja z systemem

- [ ] `voice_cortex.py` - fasada, kolejkowanie, personality-aware TTS
- [ ] Homeostasis integration (Phase 12, health monitoring)
- [ ] K1 Perception events (VOICE source)
- [ ] Consciousness -> TTS parametry (emocja, tempo)
- [ ] REPL `/voice` command
- [ ] Testy: 20+
- [ ] **Szacowany czas:** 1 sesja

### Faza 4: Telegram Voice
**Cel:** Maria slucha i mowi przez Telegram

- [ ] Telegram voice message handler (OGA -> WAV -> STT)
- [ ] Telegram voice reply (TTS -> WAV -> OGA -> send_voice)
- [ ] FFmpeg integration
- [ ] Testy: 15+
- [ ] **Szacowany czas:** 0.5 sesji

---

## 9. REPL Commands

```
/voice              - Status modulu glosu
/voice speak <text> - Powiedz tekst (debug: odtworz lokalnie)
/voice listen       - Nasluchuj (debug: z mikrofonu mini PC)
/voice voices       - Lista dostepnych glosow
/voice model        - Aktualny model STT + TTS
/voice health       - Zdrowie modulu
/voice test         - Self-test (TTS -> WAV -> STT -> porownaj)
```

---

## 10. Web UI Endpoints

```
GET  /api/voice/status          - Stan modulu (TTS/STT loaded, health)
GET  /api/voice/voices          - Lista glosow Piper
POST /api/voice/speak           - TTS: tekst -> audio (WAV response)
POST /api/voice/transcribe      - STT: audio upload -> tekst
POST /api/voice/config          - Zmien config (voice, speed, auto_speak)
```

---

## 11. Ograniczenia i ryzyka

| Ryzyko | Prawdopodobienstwo | Wplyw | Mitygacja |
|--------|-------------------|-------|-----------|
| Whisper slow na CPU | Niskie (small model = 6x RT) | Sredni | Upgrade do medium lub tryb async |
| Piper glos brzmi robotycznie | Srednie | Niski | Mozliwosc zmiany glsu, fine-tuning |
| RAM pressure z STT | Niskie (2GB/32GB) | Sredni | Lazy loading, unload po idle |
| Browser mic permission | Niskie | Niski | Fallback na tekst, HTTPS required |
| Halas w tle (STT) | Srednie | Sredni | VAD threshold tuning, noise gate |
| Latencja end-to-end | Niskie | Sredni | Streaming TTS, parallel processing |

---

## 12. Zaleznosci (nowe pakiety)

```
piper-tts>=2.0.0      # TTS engine (ONNX)
faster-whisper>=1.0.0  # STT engine (CTranslate2)
silero-vad>=5.0        # Voice Activity Detection
# ffmpeg (system package, apt install ffmpeg)
```

**Brak nowych ciezkich deps** - wszystkie lekkie, CPU-friendly, offline.

---

## 13. ADR (Architecture Decision Records)

### ADR-029: Piper TTS zamiast Coqui
- Piper: 300MB RAM, 20ms latencja, 4 polskie glosy, aktywnie rozwijany
- Coqui: 5GB RAM, sekundy latencji na CPU, firma zamknieta 2025
- Decyzja: Piper jako domyslny TTS, Coqui jako opcjonalny upgrade (voice cloning)

### ADR-030: faster-whisper small zamiast large
- large-v3: 10GB RAM (za duzo), najlepsza dokladnosc
- small INT8: 2GB RAM, WER ~10% dla polskiego, 6x realtime
- Decyzja: small jako default, upgrade path do medium (5GB) jesli potrzeba
- Whisper ladowany on-demand (cold start), nie warm (oszczednosc RAM)

### ADR-031: VAD przed STT (Silero gate)
- Bez VAD: Whisper transkrybuje cisze i szumy (marnowanie CPU)
- Z VAD: tylko segmenty z mowa ida do Whisper (~90% oszczednosc CPU)
- Silero VAD: 1MB model, <1ms, zaniedbywalny narzut

### ADR-032: WebSocket audio streaming zamiast HTTP upload
- HTTP: caly plik audio -> upload -> transcribe (wysoka latencja)
- WebSocket: chunki 30ms -> VAD -> incremental STT (niska latencja)
- Maria juz uzywa Flask-SocketIO w Web UI - naturalne rozszerzenie

---

*Ostatnia aktualizacja: 2026-04-06*
