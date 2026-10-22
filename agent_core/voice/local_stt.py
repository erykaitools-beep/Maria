"""Bounded local WAV transcription through the pinned whisper.cpp CLI contract."""
from collections import deque
import io
import json
import os
from pathlib import Path
import signal
import struct
import subprocess
import tempfile
import threading
import time
import wave

MAX_AUDIO_BYTES = 1024 * 1024
MAX_SECONDS = 30
SAMPLE_RATE = 16000
PROVIDER = "whisper.cpp"
LANGUAGE = "pl"


class STTError(RuntimeError):
    """An intentionally public, path-free failure."""
    def __init__(self, code, message, status=400):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def validate_wav(data):
    """Accept complete uncompressed PCM16 mono WAV only, before inference."""
    if not data or len(data) > MAX_AUDIO_BYTES:
        raise STTError("invalid_audio", "Nieprawidłowy rozmiar nagrania.", 413 if data else 400)
    if len(data) < 44 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise STTError("invalid_audio", "Wymagany jest plik WAV PCM16 mono 16 kHz.")
    # Validate chunk boundaries ourselves: wave can accept truncated data chunks.
    declared = struct.unpack_from("<I", data, 4)[0] + 8
    if declared != len(data):
        raise STTError("invalid_audio", "Nagranie WAV jest niekompletne.")
    offset, audio_chunks, format_chunks = 12, 0, 0
    while offset < len(data):
        if offset + 8 > len(data):
            raise STTError("invalid_audio", "Nieprawidłowy nagłówek WAV.")
        size = struct.unpack_from("<I", data, offset + 4)[0]
        end = offset + 8 + size
        if end > len(data):
            raise STTError("invalid_audio", "Nagranie WAV jest niekompletne.")
        if data[offset:offset + 4] == b"data":
            audio_chunks += 1
            if size == 0 or size % 2:
                raise STTError("invalid_audio", "Nieprawidłowa długość danych PCM16.")
        if data[offset:offset + 4] == b"fmt ":
            format_chunks += 1
            if size < 16 or struct.unpack_from("<HHIIHH", data, offset + 8) != (1, 1, SAMPLE_RATE, SAMPLE_RATE * 2, 2, 16):
                raise STTError("invalid_audio", "Wymagany jest poprawny WAV PCM16 mono 16 kHz.")
        offset = end + (size & 1)
    if offset != len(data) or audio_chunks != 1 or format_chunks != 1:
        raise STTError("invalid_audio", "Nieprawidłowa struktura WAV.")
    try:
        with wave.open(io.BytesIO(data), "rb") as audio:
            frames = audio.getnframes()
            if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate(), audio.getcomptype()) != (1, 2, SAMPLE_RATE, "NONE"):
                raise STTError("invalid_audio", "Wymagany jest WAV PCM16 mono 16 kHz.")
            if not 0 < frames <= MAX_SECONDS * SAMPLE_RATE:
                raise STTError("invalid_audio", "Nagranie musi trwać od ponad zera do 30 sekund.")
            if len(audio.readframes(frames + 1)) != frames * 2:
                raise STTError("invalid_audio", "Nagranie WAV jest niekompletne.")
    except (wave.Error, EOFError, OSError, struct.error):
        raise STTError("invalid_audio", "Nie można odczytać nagrania WAV.") from None
    return data


class LocalSTT:
    """One task at a time, no network, no shell, no automatic chat submission."""
    def __init__(self, binary_path=None, model_path=None, timeout_s=45,
                 rate_count=6, rate_window_s=60, *, popen=None, clock=None,
                 kill_group=None, temp_parent=None):
        self.binary = binary_path if binary_path is not None else os.environ.get("MARIA_STT_BIN", "")
        self.model = model_path if model_path is not None else os.environ.get("MARIA_STT_MODEL", "")
        self.timeout_s = max(1, min(90, float(timeout_s)))
        self.rate_count = max(1, min(60, int(rate_count)))
        self.rate_window_s = max(1, float(rate_window_s))
        self._popen = popen or subprocess.Popen
        self._clock = clock or time.monotonic
        self._kill_group = kill_group or os.killpg
        self._temp_parent = temp_parent
        self._semaphore = threading.BoundedSemaphore(1)
        self._attempts = deque(maxlen=self.rate_count)

    def available(self):
        try:
            return bool(self.binary and self.model and Path(self.binary).is_absolute()
                        and Path(self.model).is_absolute() and Path(self.binary).is_file()
                        and os.access(self.binary, os.X_OK) and Path(self.model).is_file()
                        and os.access(self.model, os.R_OK) and Path(self.model).stat().st_size > 0)
        except (OSError, ValueError, TypeError):
            return False

    def status(self):
        return {"available": self.available(), "provider": PROVIDER,
                "language": LANGUAGE, "max_seconds": MAX_SECONDS,
                "sample_rate": SAMPLE_RATE}

    def transcribe(self, data):
        return self.transcribe_stream(io.BytesIO(data), len(data))

    def transcribe_stream(self, stream, content_length=None):
        if content_length is not None and (content_length < 0 or content_length > MAX_AUDIO_BYTES):
            raise STTError("too_large", "Nagranie przekracza limit 1 MiB.", 413)
        if not self.available():
            raise STTError("unavailable", "Lokalne rozpoznawanie mowy nie jest skonfigurowane.", 503)
        if not self._semaphore.acquire(blocking=False):
            raise STTError("busy", "Trwa rozpoznawanie poprzedniego nagrania.", 409)
        try:
            now = self._clock()
            while self._attempts and self._attempts[0] <= now - self.rate_window_s:
                self._attempts.popleft()
            if len(self._attempts) >= self.rate_count:
                raise STTError("rate_limited", "Limit nagrań. Spróbuj za chwilę.", 429)
            self._attempts.append(now)
            try:
                data = stream.read(MAX_AUDIO_BYTES + 1)
            except (OSError, ValueError):
                raise STTError("invalid_audio", "Nie można odczytać nagrania.") from None
            if len(data) > MAX_AUDIO_BYTES:
                raise STTError("too_large", "Nagranie przekracza limit 1 MiB.", 413)
            if content_length is not None and len(data) != content_length:
                raise STTError("invalid_audio", "Nagranie jest niekompletne.")
            validate_wav(data)
            return self._invoke(data)
        finally:
            self._semaphore.release()

    def _cleanup_process(self, process):
        # Also kill descendants if the CLI leader has already exited.
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                self._kill_group(process.pid, sig)
            except (ProcessLookupError, PermissionError, OSError):
                pass
            if sig == signal.SIGTERM:
                try:
                    process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    pass
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            pass

    def _invoke(self, data):
        with tempfile.TemporaryDirectory(prefix="maria-stt-", dir=self._temp_parent) as directory:
            root = Path(directory)
            audio = root / "input.wav"
            prefix = root / "result"
            audio.write_bytes(data)
            command = [self.binary, "--model", self.model, "--file", str(audio),
                       "--language", LANGUAGE, "--threads", "2", "--no-gpu",
                       "--output-json", "--output-file", str(prefix), "--no-prints"]
            process = None
            try:
                process = self._popen(command, stdin=subprocess.DEVNULL,
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                      cwd=directory, start_new_session=True,
                                      env={"PATH": os.defpath, "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
                                           "OMP_NUM_THREADS": "2", "OPENBLAS_NUM_THREADS": "2"})
                if process.wait(timeout=self.timeout_s) != 0:
                    raise STTError("transcription_failed", "Lokalne rozpoznawanie mowy zakończyło się błędem.", 502)
                result_path = root / "result.json"
                if result_path.is_symlink() or not result_path.is_file() or result_path.stat().st_size > 128 * 1024:
                    raise STTError("invalid_result", "Nieprawidłowy wynik rozpoznawania.", 502)
                with result_path.open("rb") as handle:
                    raw = handle.read(128 * 1024 + 1)
                result = json.loads(raw)
                segments = result.get("transcription") if isinstance(result, dict) else None
                if not isinstance(segments, list) or any(not isinstance(s, dict) or not isinstance(s.get("text"), str) for s in segments):
                    raise STTError("invalid_result", "Nieprawidłowy wynik rozpoznawania.", 502)
                text = " ".join(s["text"].strip() for s in segments).strip()
                if len(text) > 2000:
                    raise STTError("invalid_result", "Rozpoznany tekst jest zbyt długi.", 502)
                return text
            except subprocess.TimeoutExpired:
                raise STTError("timeout", "Lokalne rozpoznawanie mowy przekroczyło czas oczekiwania.", 504) from None
            except STTError:
                raise
            except (OSError, ValueError, TypeError, UnicodeError):
                raise STTError("transcription_failed", "Nie można wykonać lokalnego rozpoznawania mowy.", 502) from None
            finally:
                if process is not None:
                    self._cleanup_process(process)
