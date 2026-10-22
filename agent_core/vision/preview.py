"""Bounded, off-tick publication of the latest camera preview.

Continuous perception is independent of viewers. JPEG encoding and file IO
run on one worker; pending notifications coalesce instead of growing a queue.
Unified UI readers use memory. Compatibility files are atomically refreshed
at most once every five seconds, even while a viewer watches at one FPS.
"""
import copy
import json
import logging
import os
import tempfile
import threading
import time
from pathlib import Path

logger = logging.getLogger(__name__)


def percept_state(percept):
    """Stable UI representation shared by live preview and manual snapshots."""
    data = {
        "timestamp": percept.timestamp, "summary": percept.summary,
        "quality": round(percept.quality, 3),
        "health": round(percept.vision_health.overall, 3),
        "modules_run": list(percept.modules_run), "sensor_id": percept.sensor_id,
        "processing_time_ms": percept.total_processing_time_ms,
    }
    if percept.motion:
        m = percept.motion
        data["motion"] = {"motion_detected": m.motion_detected,
                          "motion_level": round(m.motion_level, 3),
                          "classification": m.classification.value,
                          "alert_level": m.alert_level.value,
                          "regions_count": len(m.regions)}
    if percept.scene:
        s = percept.scene
        data["scene"] = {"description": s.description, "lighting": s.lighting,
                         "dominant_colors": list(s.dominant_colors),
                         "complexity": round(s.complexity, 3),
                         "backend_used": s.backend_used}
    return data


def encode_jpeg(image):
    import cv2
    ok, buffer = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 80])
    if not ok:
        raise ValueError("camera frame could not be encoded")
    return buffer.tobytes()


def atomic_write(path, content):
    """Readers see the complete old or new file, never a partially written one."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix="." + path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


class VisionPreviewPublisher:
    def __init__(self, cortex, directory, *, interval=1.0, disk_interval=5.0,
                 viewer_ttl=15.0, encoder=encode_jpeg, clock=time.monotonic):
        self.cortex = cortex
        self.directory = Path(directory)
        self.interval = max(0.01, interval)
        self.disk_interval = max(self.interval, disk_interval)
        self.viewer_ttl = viewer_ttl
        self._encoder, self._clock = encoder, clock
        self._lock = threading.Lock()
        self._pending = threading.Event()
        self._closed = threading.Event()
        self._thread = None
        self._viewer_until = 0.0
        self._last_disk = float("-inf")
        self._state, self._jpeg = None, None
        self._frame_version = None
        self._frame_percept = None

    def notify(self):
        """Constant-size handoff; never encode or write from the tick thread."""
        with self._lock:
            if self._closed.is_set():
                return
            if self._thread is None:
                self._thread = threading.Thread(target=self._run, name="VisionPreview", daemon=True)
                try:
                    self._thread.start()
                except RuntimeError:
                    self._thread = None
                    raise
        self._pending.set()

    def touch_viewer(self):
        with self._lock:
            self._viewer_until = self._clock() + self.viewer_ttl
        self.notify()

    def state(self):
        with self._lock:
            return copy.deepcopy(self._state)

    def frame(self, version=None):
        with self._lock:
            if version is not None and version != self._frame_version:
                return None
            return self._jpeg

    def _run(self):
        last = float("-inf")
        while not self._closed.is_set():
            self._pending.wait()
            if self._closed.is_set():
                break
            if self._closed.wait(max(0.0, self.interval - (self._clock() - last))):
                break
            self._pending.clear()
            last = self._clock()
            try:
                self._publish()
            except Exception:
                logger.debug("Vision preview publication failed", exc_info=True)

    def _publish(self):
        state, image = self.cortex.preview_snapshot()
        if state is None:
            return
        now = self._clock()
        due = now - self._last_disk >= self.disk_interval
        with self._lock:
            viewed = now < self._viewer_until
            jpeg, version = self._jpeg, self._frame_version
            frame_percept = self._frame_percept
        timestamp = str(state["last_percept"]["timestamp"])
        if image is None:
            jpeg, version = None, None
            frame_percept = None
        elif (due or viewed) and timestamp != version:
            jpeg, version = self._encoder(image), timestamp
            frame_percept = copy.deepcopy(state["last_percept"])
        state["frame_version"] = version
        state["frame_available"] = jpeg is not None
        state["frame_percept"] = frame_percept
        with self._lock:
            self._state, self._jpeg, self._frame_version = state, jpeg, version
            self._frame_percept = frame_percept
        if due:
            # Throttle retries too: a broken disk must not add IO to every tick.
            self._last_disk = now
            if jpeg is not None:
                atomic_write(self.directory / "vision_frame.jpg", jpeg)
            atomic_write(self.directory / "vision_state.json", json.dumps(state, ensure_ascii=False).encode())

    def close(self, timeout=1.0):
        self._closed.set()
        self._pending.set()
        with self._lock:
            thread = self._thread
        if thread is not None:
            thread.join(timeout)
