# M.A.R.I.A. - Voice Module Specification (Mouth + Ears)

> **Created:** 2026-04-06
> **Status:** Specification (pending implementation)
> **Philosophy:** Voice as an organ - Maria speaks and listens, she does not "play back audio"
> **Approach:** Offline-first, graceful degradation, incremental implementation

---

## 1. Guiding principle: Biological inspiration

### Human voice vs. synthesizer

| Aspect | Classic synthesizer | Human voice | M.A.R.I.A. Voice |
|--------|---------------------|-------------|-------------------|
| Failure | 0 or 1 | Hoarseness, whisper | Graceful degradation |
| Emotion | None | Tone, pace, accent | Personality-aware TTS |
| Hearing | None | Selective (cocktail party) | VAD + Whisper |
| Adaptation | None | Louder in noise | Dynamic parameters |
| Memory | None | Recognizes voices | Speaker ID (future) |

### Graceful Degradation - voice

```
FULL VOICE (100%)
    |
    v CPU load
SLOWER VOICE (80%) - longer TTS response time
    |
    v no TTS model
TEXT ONLY (60%) - text only, no audio
    |
    v no STT model
ONE-WAY VOICE (40%) - Maria speaks but does not hear
    |
    v no microphone/speaker
SILENT MODE (0%) - text only (as now)
```

Maria NEVER says "the voice module is broken" - she says "I'm a bit hoarse" or "I can barely hear you".

---

## 2. Layered architecture

```
+-------------------------------------------------------------+
|                    MARIA CONSCIOUSNESS                       |
|            (Unified Perception - a single "self")           |
+-------------------------------------------------------------+
|                    VOICE CORTEX                              |
|     Speech/hearing coordination, queueing                   |
|     Personality-aware TTS parameters                        |
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

## 3. Technology stack

### 3.1 TTS - Piper (Mouth)

| Parameter | Value |
|----------|---------|
| **Engine** | Piper TTS (ONNX, offline) |
| **Voice** | `pl_PL-gosia-medium` (female, Polish) |
| **Format** | 22050 Hz, 16-bit PCM mono |
| **Latency** | 20-30ms on CPU (Ryzen 5) |
| **RAM** | ~300 MB |
| **Disk** | ~80 MB (.onnx model + .json) |
| **Streaming** | `synthesize_stream_raw()` - chunked PCM |
| **Pip** | `piper-tts` |

**Why Piper and not Coqui:**
- Coqui: ~5GB RAM, seconds of latency on CPU, closed-source company
- Piper: ~300MB RAM, 20ms latency, actively developed
- Piper has 4 Polish voices (gosia = natural female)

### 3.2 STT - faster-whisper (Ears)

| Parameter | Value |
|----------|---------|
| **Engine** | faster-whisper (CTranslate2) |
| **Model** | `small` (INT8 quantized) |
| **Language** | Polish (`pl`) |
| **WER** | ~10% (acceptable for conversation) |
| **RAM** | ~2 GB |
| **Disk** | ~250 MB |
| **Latency** | <1s for a 5s utterance |
| **Pip** | `faster-whisper` |

**Why `small` and not `large-v3`:**
- large-v3: ~10GB RAM (too much alongside Ollama)
- small INT8: ~2GB RAM, 6x realtime, sufficient accuracy
- Option to upgrade to `medium` (5GB) if needed

### 3.3 VAD - Silero (Speech detection)

| Parameter | Value |
|----------|---------|
| **Engine** | Silero VAD v6 |
| **Model** | ONNX (1-2 MB) |
| **Latency** | <1ms per 30ms chunk |
| **CPU** | 0.43% (negligible) |
| **Pip** | `silero-vad` |

**Role:** Detects the start/end of speech in the audio stream. Saves CPU - Whisper transcribes only segments that contain speech, not silence.

### 3.4 Resource budget

| Resource | Current use | Voice module | Total | Limit |
|-------|---------------|-------------|---------|-------|
| **RAM** | ~12 GB (Ollama) | ~2.3 GB | ~14.3 GB | 32 GB |
| **CPU** | Variable | <5% idle, peak on STT | OK | 6 cores |
| **Disk** | ~6 GB models | ~330 MB | ~6.3 GB | 1 TB |

---

## 4. File structure

```
agent_core/voice/
  __init__.py          # VoiceModule facade + run_voice_pipeline()
  voice_cortex.py      # TTS/STT coordination, queueing, personality
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

## 5. Interfaces (API)

### 5.1 VoiceCortex - Main facade

```python
class VoiceCortex:
    """Coordinate speech and hearing."""

    def speak(self, text: str, emotion: str = "neutral") -> bytes:
        """
        Convert text to speech (PCM audio).

        Args:
            text: Text to speak
            emotion: Emotion (neutral, happy, sad, excited) - affects pace/tone

        Returns:
            Raw PCM bytes (22050 Hz, 16-bit mono)
        """

    def speak_stream(self, text: str) -> Iterator[bytes]:
        """
        Streaming TTS - returns audio chunks as they are generated.
        For the Web UI WebSocket (low latency).
        """

    def listen(self, audio: bytes, sample_rate: int = 16000) -> str:
        """
        Convert speech to text.

        Args:
            audio: Raw PCM bytes
            sample_rate: Sample rate (default 16kHz)

        Returns:
            Transcribed text
        """

    def listen_stream(self, audio_chunks: Iterator[bytes]) -> str:
        """
        Streaming STT with VAD - buffers chunks, transcribes speech segments.
        For the Web UI WebSocket (real-time).
        """

    def get_health(self) -> VoiceHealth:
        """Health state of the voice module (TTS loaded, STT loaded, latency)."""

    def is_available(self) -> bool:
        """Whether the voice module is available (at least TTS)."""
```

### 5.2 PiperTTS - Speech engine

```python
class PiperTTS:
    """Wrapper around Piper TTS."""

    def __init__(self, voice: str = "pl_PL-gosia-medium", data_dir: str = "models/piper/"):
        """
        Args:
            voice: Piper voice name (from the voices directory)
            data_dir: Directory with .onnx models
        """

    def synthesize(self, text: str, speed: float = 1.0) -> bytes:
        """Whole text -> whole audio (PCM)."""

    def synthesize_stream(self, text: str, speed: float = 1.0) -> Iterator[bytes]:
        """Text -> audio chunks (streaming, low latency)."""

    def set_voice(self, voice: str) -> None:
        """Change voice (reload the model)."""

    def get_available_voices(self) -> List[str]:
        """List available voices in data_dir."""
```

### 5.3 WhisperSTT - Hearing engine

```python
class WhisperSTT:
    """Wrapper around faster-whisper."""

    def __init__(self, model_size: str = "small", compute_type: str = "int8"):
        """
        Args:
            model_size: tiny/base/small/medium/large-v3
            compute_type: int8/float16/float32
        """

    def transcribe(self, audio: bytes, language: str = "pl") -> TranscriptionResult:
        """
        Transcribe audio.

        Returns:
            TranscriptionResult(text, language, confidence, segments)
        """

    def detect_language(self, audio: bytes) -> str:
        """Detect language from the first 30s of audio."""
```

### 5.4 SileroVAD - Speech detection

```python
class SileroVAD:
    """Voice Activity Detection."""

    def __init__(self, threshold: float = 0.5, min_speech_ms: int = 250):
        """
        Args:
            threshold: Decision threshold (0.0-1.0)
            min_speech_ms: Minimum speech length (filters out noise)
        """

    def process_chunk(self, chunk: bytes) -> bool:
        """Does the chunk contain speech? (True/False)"""

    def get_speech_segments(self, audio: bytes) -> List[Tuple[float, float]]:
        """Return speech segments [(start_s, end_s), ...]"""

    def reset(self) -> None:
        """Reset state (new listening session)."""
```

---

## 6. Integration with existing systems

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
[Server: brain.think(text)]  <-- existing pipeline
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

**New SocketIO events:**

```python
# Client -> Server
@socketio.on('voice_start')      # Start listening
@socketio.on('voice_audio')      # Audio chunk (PCM bytes)
@socketio.on('voice_stop')       # Stop listening

# Server -> Client
socketio.emit('voice_transcript') # Real-time transcription
socketio.emit('voice_response')   # Response audio (PCM chunks)
socketio.emit('voice_status')     # State (listening, thinking, speaking)
```

**Web UI changes:**
- Microphone button in the chat (next to the text field)
- Speaker button next to Maria's responses (play with voice)
- "always speak" option in settings (Maria speaks every response)

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
[brain.think(text)]  <-- existing pipeline
     | response text
     v
[PiperTTS.synthesize()]
     | WAV audio
     v
[FFmpeg: WAV -> OGG Opus]
     v
[bot.send_voice(chat_id, ogg)]
```

**New handler in `agent_core/telegram/`:**

```python
# telegram_bridge.py - new handler
def handle_voice_message(update):
    """Handle voice messages from the operator."""
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
# Personality affects TTS parameters
personality = consciousness.get_traits()
speed = 1.0 + (personality.get("curiosity", 0.5) - 0.5) * 0.2  # more curious = faster
# Emotion from ExperienceTracker -> emotion parameter
emotion = experience_tracker.get_current_emotion()
audio = voice_cortex.speak(text, emotion=emotion)
```

### 6.5 K1 Perception - New events

```python
# New PerceptionSource and event types
class PerceptionSource(Enum):
    VOICE = "voice"           # New

class VoiceEventType:
    SPEECH_DETECTED = "speech_detected"     # VAD detected speech
    SPEECH_TRANSCRIBED = "speech_transcribed" # STT finished
    SPEECH_SYNTHESIZED = "speech_synthesized" # TTS finished
    VOICE_ERROR = "voice_error"              # Module error
```

---

## 7. Configuration

### 7.1 .env

```bash
# --- Voice Module ---
# Enable the voice module (default false)
VOICE_ENABLED=false

# TTS: Piper voice (pl_PL-gosia-medium, pl_PL-darkman-medium)
VOICE_TTS_MODEL=pl_PL-gosia-medium

# STT: Whisper model (tiny/base/small/medium)
VOICE_STT_MODEL=small

# STT: compute type (int8/float16)
VOICE_STT_COMPUTE=int8

# VAD: speech detection threshold (0.0-1.0)
VOICE_VAD_THRESHOLD=0.5

# Web UI: automatic voice playback (true/false)
VOICE_AUTO_SPEAK=false

# Telegram: reply with voice to voice messages (true/false)
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
    startup="warm",     # loaded at startup if VOICE_ENABLED
    mutex=False,        # does not conflict with others
    notes="Piper TTS pl_PL-gosia-medium, ONNX, CPU"
)

MODEL_08 = ModelSpec(
    role=ModelRole.HEARING,
    name="whisper-small-int8",
    size_gb=0.25,
    ram_tier="M",       # ~2GB in RAM
    startup="cold",     # loaded on-demand (on first voice input)
    mutex=False,
    notes="faster-whisper small INT8, CPU, Polish"
)
```

---

## 8. Implementation plan (4 phases)

### Phase 1: TTS - Maria speaks (MVP)
**Goal:** Maria can convert text to speech

- [ ] `tts_engine.py` - PiperTTS wrapper
- [ ] `voice_model.py` - dataclasses (VoiceConfig, VoiceEvent, VoiceHealth)
- [ ] `audio_io.py` - PCM/WAV/OGG conversion
- [ ] Download the `pl_PL-gosia-medium` voice
- [ ] Web UI: speaker button next to responses
- [ ] Tests: 30+
- [ ] **Estimated time:** 1 session

### Phase 2: STT - Maria listens
**Goal:** Maria understands speech (transcription)

- [ ] `stt_engine.py` - WhisperSTT wrapper
- [ ] `vad.py` - SileroVAD wrapper
- [ ] Web UI: microphone button + streaming audio
- [ ] WebSocket events (voice_start, voice_audio, voice_stop)
- [ ] Tests: 30+
- [ ] **Estimated time:** 1 session

### Phase 3: Voice Cortex - Full integration
**Goal:** Coordinate speech/hearing, integrate with the system

- [ ] `voice_cortex.py` - facade, queueing, personality-aware TTS
- [ ] Homeostasis integration (Phase 12, health monitoring)
- [ ] K1 Perception events (VOICE source)
- [ ] Consciousness -> TTS parameters (emotion, pace)
- [ ] REPL `/voice` command
- [ ] Tests: 20+
- [ ] **Estimated time:** 1 session

### Phase 4: Telegram Voice
**Goal:** Maria listens and speaks through Telegram

- [ ] Telegram voice message handler (OGA -> WAV -> STT)
- [ ] Telegram voice reply (TTS -> WAV -> OGA -> send_voice)
- [ ] FFmpeg integration
- [ ] Tests: 15+
- [ ] **Estimated time:** 0.5 session

---

## 9. REPL Commands

```
/voice              - Voice module status
/voice speak <text> - Speak text (debug: play locally)
/voice listen       - Listen (debug: from the mini PC microphone)
/voice voices       - List available voices
/voice model        - Current STT + TTS model
/voice health       - Module health
/voice test         - Self-test (TTS -> WAV -> STT -> compare)
```

---

## 10. Web UI Endpoints

```
GET  /api/voice/status          - Module state (TTS/STT loaded, health)
GET  /api/voice/voices          - List of Piper voices
POST /api/voice/speak           - TTS: text -> audio (WAV response)
POST /api/voice/transcribe      - STT: audio upload -> text
POST /api/voice/config          - Change config (voice, speed, auto_speak)
```

---

## 11. Limitations and risks

| Risk | Likelihood | Impact | Mitigation |
|--------|-------------------|-------|-----------|
| Whisper slow on CPU | Low (small model = 6x RT) | Medium | Upgrade to medium or async mode |
| Piper voice sounds robotic | Medium | Low | Option to change voice, fine-tuning |
| RAM pressure from STT | Low (2GB/32GB) | Medium | Lazy loading, unload after idle |
| Browser mic permission | Low | Low | Fallback to text, HTTPS required |
| Background noise (STT) | Medium | Medium | VAD threshold tuning, noise gate |
| End-to-end latency | Low | Medium | Streaming TTS, parallel processing |

---

## 12. Dependencies (new packages)

```
piper-tts>=2.0.0      # TTS engine (ONNX)
faster-whisper>=1.0.0  # STT engine (CTranslate2)
silero-vad>=5.0        # Voice Activity Detection
# ffmpeg (system package, apt install ffmpeg)
```

**No new heavy deps** - all lightweight, CPU-friendly, offline.

---

## 13. ADR (Architecture Decision Records)

### ADR-029: Piper TTS instead of Coqui
- Piper: 300MB RAM, 20ms latency, 4 Polish voices, actively developed
- Coqui: 5GB RAM, seconds of latency on CPU, went closed-source in 2025
- Decision: Piper as the default TTS, Coqui as an optional upgrade (voice cloning)

### ADR-030: faster-whisper small instead of large
- large-v3: 10GB RAM (too much), best accuracy
- small INT8: 2GB RAM, WER ~10% for Polish, 6x realtime
- Decision: small as the default, upgrade path to medium (5GB) if needed
- Whisper loaded on-demand (cold start), not warm (saves RAM)

### ADR-031: VAD before STT (Silero gate)
- Without VAD: Whisper transcribes silence and noise (wasted CPU)
- With VAD: only segments with speech go to Whisper (~90% CPU savings)
- Silero VAD: 1MB model, <1ms, negligible overhead

### ADR-032: WebSocket audio streaming instead of HTTP upload
- HTTP: whole audio file -> upload -> transcribe (high latency)
- WebSocket: 30ms chunks -> VAD -> incremental STT (low latency)
- Maria already uses Flask-SocketIO in the Web UI - a natural extension

---

*Last updated: 2026-04-06*
