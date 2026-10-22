"""One bounded asynchronous manual snapshot job for the authenticated UI."""
import copy
import logging
import threading
import time
import uuid

from .preview import encode_jpeg, percept_state

logger = logging.getLogger(__name__)


class SnapshotBusy(Exception):
    pass


class VisionSnapshotService:
    def __init__(self, cortex, *, encoder=encode_jpeg, clock=time.monotonic,
                 ttl=300.0, cooldown=5.0):
        self.cortex = cortex
        self._encoder, self._clock = encoder, clock
        self._ttl, self._cooldown = ttl, cooldown
        self._lock = threading.Lock()
        self._job = None
        self._jpeg = None
        self._thread = None
        self._completed_at = float("-inf")
        self._closed = False

    def request(self):
        with self._lock:
            if self._closed:
                raise SnapshotBusy("Obsluga zdjec jest wylaczona.")
            if self._job and self._job["status"] == "running":
                raise SnapshotBusy("Zdjecie jest juz przygotowywane.")
            if self._clock() - self._completed_at < self._cooldown:
                raise SnapshotBusy("Odczekaj chwile przed kolejnym zdjeciem.")
            job_id = uuid.uuid4().hex
            self._job = {"job_id": job_id, "status": "running", "success": False}
            self._jpeg = None
            self._thread = threading.Thread(target=self._run, args=(job_id,),
                                            name="VisionSnapshot", daemon=True)
            try:
                self._thread.start()
            except RuntimeError:
                self._job, self._thread = None, None
                raise SnapshotBusy("Nie mozna teraz przygotowac zdjecia.") from None
            return job_id

    def _run(self, job_id):
        jpeg = None
        try:
            percept, image = self.cortex.perceive_snapshot_with_frame()
            if percept is None or image is None or percept.quality <= 0:
                raise ValueError("Nie mozna zrobic zdjecia: kamera nie dostarczyla obrazu.")
            jpeg = self._encoder(image)
            result = {"job_id": job_id, "status": "done", "success": True,
                      "percept": percept_state(percept), "summary": percept.summary,
                      "quality": percept.quality}
        except Exception:
            logger.debug("Manual vision snapshot failed", exc_info=True)
            result = {"job_id": job_id, "status": "error", "success": False,
                      "error": "Nie udalo sie zrobic lub opisac zdjecia. Sprawdz stan kamery."}
        with self._lock:
            if not self._closed:
                self._job, self._jpeg = result, jpeg
                self._completed_at = self._clock()

    def _valid(self, job_id):
        return (not self._closed and self._job is not None
                and self._job["job_id"] == job_id
                and (self._job["status"] == "running"
                     or self._clock() - self._completed_at < self._ttl))

    def result(self, job_id):
        with self._lock:
            return copy.deepcopy(self._job) if self._valid(job_id) else None

    def frame(self, job_id):
        with self._lock:
            return self._jpeg if self._valid(job_id) else None

    def close(self, timeout=1.0):
        with self._lock:
            self._closed = True
            thread = self._thread
        if thread is not None:
            thread.join(timeout)
