"""Offline tests: no model, network or real native process is invoked."""
import io
import json
from pathlib import Path
import signal
import struct
import subprocess
import tempfile
import threading
import unittest
import wave

from agent_core.voice.local_stt import LocalSTT, MAX_AUDIO_BYTES, STTError, validate_wav


def wav(seconds=0.01, channels=1, width=2, rate=16000):
    output = io.BytesIO()
    with wave.open(output, "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(width)
        handle.setframerate(rate)
        handle.writeframes(b"\0" * int(seconds * rate) * channels * width)
    return output.getvalue()


class LocalSTTTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="test-stt-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.binary = self.root / "whisper-cli"
        self.binary.write_bytes(b"not executable test data")
        self.binary.chmod(0o700)
        self.model = self.root / "model.bin"
        self.model.write_bytes(b"not a real model")
        self.calls, self.kills, self.folders = [], [], []

    def backend(self, **kwargs):
        return LocalSTT(str(self.binary), str(self.model), temp_parent=self.root,
                        popen=kwargs.pop("popen", self.fake_process),
                        kill_group=lambda pid, sig: self.kills.append((pid, sig)), **kwargs)

    def fake_process(self, args, **options):
        self.calls.append((args, options))
        root = Path(options["cwd"])
        self.folders.append(root)
        self.assertTrue((root / "input.wav").is_file())
        (root / "result.json").write_text(json.dumps({"transcription": [{"text": " Próba "}, {"text": "po polsku."}]}))
        class Process:
            pid = 987654321
            def wait(self, timeout=None):
                return 0
        return Process()

    def test_success_contract_args_private_cleanup(self):
        backend = self.backend()
        self.assertEqual(backend.transcribe(wav()), "Próba po polsku.")
        args, options = self.calls[0]
        self.assertIn("--no-gpu", args)
        self.assertEqual(args[args.index("--language") + 1], "pl")
        self.assertEqual(args[args.index("--threads") + 1], "2")
        self.assertEqual(args[0], str(self.binary))
        self.assertEqual(options["start_new_session"], True)
        self.assertNotIn("shell", options)
        self.assertNotIn("MARIA_SECRET_KEY", options["env"])
        self.assertTrue(all(not path.exists() for path in self.folders))
        self.assertEqual([s for _, s in self.kills], [signal.SIGTERM, signal.SIGKILL])

    def test_availability_never_starts_model(self):
        backend = self.backend()
        self.assertTrue(backend.status()["available"])
        self.assertEqual(self.calls, [])
        self.model.unlink()
        self.assertFalse(backend.available())
        with self.assertRaises(STTError) as failure:
            backend.transcribe(wav())
        self.assertEqual(failure.exception.status, 503)
        self.assertEqual(self.calls, [])
        self.assertNotIn(str(self.root), str(failure.exception))

    def test_audio_contract_and_exact_duration_bound(self):
        validate_wav(wav(seconds=30))
        wrong_align = bytearray(wav())
        struct.pack_into("<H", wrong_align, 32, 4)
        wrong_byte_rate = bytearray(wav())
        struct.pack_into("<I", wrong_byte_rate, 28, 64000)
        for data in [b"not WAV", wav(channels=2), wav(width=1), wav(rate=8000),
                     wav(seconds=30.001), wav(seconds=0), wav()[:-1], wav() + b"junk",
                     bytes(wrong_align), bytes(wrong_byte_rate)]:
            with self.subTest(size=len(data)):
                with self.assertRaises(STTError):
                    validate_wav(data)
        self.assertEqual(self.calls, [])

    def test_oversize_declared_before_read_and_bounded_missing_length(self):
        backend = self.backend()
        class NeverRead:
            def read(self, size):
                raise AssertionError("oversize Content-Length must be rejected before read")
        with self.assertRaises(STTError) as failure:
            backend.transcribe_stream(NeverRead(), MAX_AUDIO_BYTES + 1)
        self.assertEqual(failure.exception.status, 413)
        reads = []
        class Bounded:
            def read(self, size):
                reads.append(size)
                return b"x" * size
        with self.assertRaises(STTError) as failure:
            backend.transcribe_stream(Bounded())
        self.assertEqual(failure.exception.status, 413)
        self.assertEqual(reads, [MAX_AUDIO_BYTES + 1])
        self.assertEqual(self.calls, [])

    def test_declared_truncation_and_missing_length_valid(self):
        backend = self.backend()
        with self.assertRaises(STTError):
            backend.transcribe_stream(io.BytesIO(wav()), len(wav()) + 1)
        self.assertEqual(backend.transcribe_stream(io.BytesIO(wav())), "Próba po polsku.")

    def test_global_monotonic_rate_limit_expires(self):
        now = [10.0]
        backend = self.backend(rate_count=2, clock=lambda: now[0])
        backend.transcribe(wav())
        backend.transcribe(wav())
        with self.assertRaises(STTError) as failure:
            backend.transcribe(wav())
        self.assertEqual(failure.exception.status, 429)
        now[0] += 60
        backend.transcribe(wav())
        self.assertEqual(len(self.calls), 3)

    def test_concurrent_request_is_rejected_not_queued(self):
        entered, release = threading.Event(), threading.Event()
        def process(args, **options):
            entered.set()
            self.assertTrue(release.wait(2))
            return self.fake_process(args, **options)
        backend = self.backend(popen=process)
        result = []
        def transcribe():
            try:
                result.append(backend.transcribe(wav()))
            except Exception as error:
                result.append(error)
        thread = threading.Thread(target=transcribe)
        thread.start()
        try:
            self.assertTrue(entered.wait(2))
            with self.assertRaises(STTError) as failure:
                backend.transcribe(wav())
            self.assertEqual(failure.exception.code, "busy")
        finally:
            release.set()
            thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertEqual(result, ["Próba po polsku."])

    def test_timeout_kills_group_and_cleans_files_then_releases_slot(self):
        folders = self.folders
        class TimeoutProcess:
            pid = 987654321
            first = True
            def wait(self, timeout=None):
                if self.first:
                    self.first = False
                    raise subprocess.TimeoutExpired("private-path-not-public", timeout)
                return -15
        def process(args, **options):
            folders.append(Path(options["cwd"]))
            return TimeoutProcess()
        backend = self.backend(popen=process)
        with self.assertRaises(STTError) as failure:
            backend.transcribe(wav())
        self.assertEqual(failure.exception.status, 504)
        self.assertNotIn("private-path", str(failure.exception))
        self.assertTrue(all(not p.exists() for p in self.folders))
        self.assertEqual([s for _, s in self.kills], [signal.SIGTERM, signal.SIGKILL])
        backend._popen = self.fake_process
        self.assertEqual(backend.transcribe(wav()), "Próba po polsku.")

    def test_invalid_output_and_native_failure_are_safe(self):
        for output in ["not JSON", json.dumps({"transcription": [{"text": 7}]}),
                       json.dumps({"transcription": [{"text": "x" * 2001}]}), "x" * (128 * 1024 + 1)]:
            def process(args, **options):
                proc = self.fake_process(args, **options)
                (Path(options["cwd"]) / "result.json").write_text(output)
                return proc
            with self.subTest(output_size=len(output)):
                with self.assertRaises(STTError) as failure:
                    self.backend(popen=process).transcribe(wav())
                self.assertEqual(failure.exception.status, 502)
                self.assertNotIn(str(self.root), str(failure.exception))
        self.assertTrue(all(not path.exists() for path in self.folders))


if __name__ == "__main__":
    unittest.main()
