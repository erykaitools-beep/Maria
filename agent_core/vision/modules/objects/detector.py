"""YOLO26 object detection with OpenCV preprocessing and ONNX Runtime.

The production path intentionally does not import the Ultralytics Python
runtime. Maria uses OpenCV for capture/preprocessing and loads an exported
end-to-end YOLO26 ONNX graph with ONNX Runtime. YOLO26 detection exports return
``(batch, 300, 6)`` rows in ``x1, y1, x2, y2, confidence, class_id`` format,
so no external NMS pass is required.

The module is lazy and fail-soft: a missing/incompatible model disables only
object detection.  Motion, scene statistics and on-demand VLM descriptions
continue to work.
"""

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Optional, Sequence, Tuple

import numpy as np

try:
    import cv2
except ImportError:
    cv2 = None  # type: ignore[assignment]

from agent_core.vision.modules.base import ModuleOutput
from agent_core.vision.preprocessing.preprocessor import ProcessedFrame

logger = logging.getLogger(__name__)

# Class order embedded in the official COCO-trained YOLO26 detection weights.
COCO80_LABELS: Tuple[str, ...] = (
    "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train",
    "truck", "boat", "traffic light", "fire hydrant", "stop sign",
    "parking meter", "bench", "bird", "cat", "dog", "horse", "sheep",
    "cow", "elephant", "bear", "zebra", "giraffe", "backpack", "umbrella",
    "handbag", "tie", "suitcase", "frisbee", "skis", "snowboard",
    "sports ball", "kite", "baseball bat", "baseball glove", "skateboard",
    "surfboard", "tennis racket", "bottle", "wine glass", "cup", "fork",
    "knife", "spoon", "bowl", "banana", "apple", "sandwich", "orange",
    "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair",
    "couch", "potted plant", "bed", "dining table", "toilet", "tv",
    "laptop", "mouse", "remote", "keyboard", "cell phone", "microwave",
    "oven", "toaster", "sink", "refrigerator", "book", "clock", "vase",
    "scissors", "teddy bear", "hair drier", "toothbrush",
)

_POLISH_LABELS = {
    "person": "osobe", "bicycle": "rower", "car": "samochod",
    "motorcycle": "motocykl", "airplane": "samolot", "bus": "autobus",
    "train": "pociag", "truck": "ciezarowke", "boat": "lodz",
    "bird": "ptaka", "cat": "kota", "dog": "psa", "horse": "konia",
    "backpack": "plecak", "umbrella": "parasol", "handbag": "torbe",
    "suitcase": "walizke", "bottle": "butelke", "cup": "kubek",
    "bowl": "miske", "chair": "krzeslo", "couch": "kanape",
    "potted plant": "rosline", "bed": "lozko", "dining table": "stol",
    "tv": "telewizor", "laptop": "laptop", "mouse": "mysz komputerowa",
    "remote": "pilot", "keyboard": "klawiature", "cell phone": "telefon",
    "book": "ksiazke", "clock": "zegar", "vase": "wazon",
}


@dataclass(frozen=True)
class ObjectDetection:
    """One object localized in source-image pixel coordinates."""

    class_id: int
    label: str
    confidence: float
    bbox_xyxy: Tuple[int, int, int, int]

    def to_dict(self) -> dict:
        return {
            "class_id": self.class_id,
            "label": self.label,
            "confidence": round(self.confidence, 3),
            "bbox_xyxy": list(self.bbox_xyxy),
        }


@dataclass
class ObjectOutput(ModuleOutput):
    """Fast semantic layer produced by a local object detector."""

    detections: List[ObjectDetection] = field(default_factory=list)
    backend_used: str = "none"
    image_size: Tuple[int, int] = (0, 0)  # width, height

    @property
    def labels(self) -> List[str]:
        return [d.label for d in self.detections]

    def to_dict(self) -> dict:
        d = super().to_dict()
        d.update({
            "detections": [item.to_dict() for item in self.detections],
            "backend_used": self.backend_used,
            "image_size": list(self.image_size),
        })
        return d


def describe_objects_polish(output: Optional[ObjectOutput], limit: int = 4) -> str:
    """Return a short deterministic description, with no LLM call."""
    if output is None or not output.detections:
        return ""

    # Preserve confidence order but avoid repeating the same class many times.
    seen = set()
    names = []
    for detection in output.detections:
        if detection.label in seen:
            continue
        seen.add(detection.label)
        names.append(_POLISH_LABELS.get(detection.label, detection.label))
        if len(names) >= limit:
            break
    if not names:
        return ""
    if len(names) == 1:
        joined = names[0]
    else:
        joined = ", ".join(names[:-1]) + " i " + names[-1]
    return f"Rozpoznaje {joined}."


class YOLO26ObjectModule:
    """Official YOLO26 ONNX inference, with OpenCV image processing.

    OpenCV 4.13's DNN backend loads the current end-to-end graph but produced
    corrupted TopK output in the local benchmark. ONNX Runtime is therefore a
    deliberate correctness boundary, not an optional performance preference.
    """

    def __init__(
        self,
        model_path: str,
        confidence_threshold: float = 0.50,
        input_size: int = 640,
        labels: Sequence[str] = COCO80_LABELS,
        net: Optional[Any] = None,
        intra_op_threads: int = 2,
    ):
        self._model_path = str(model_path)
        self._confidence_threshold = min(1.0, max(0.0, float(confidence_threshold)))
        self._input_size = int(input_size)
        self._labels = tuple(labels)
        self._net = net
        self._input_name: Optional[str] = None
        self._intra_op_threads = max(1, int(intra_op_threads))
        self._load_attempted = net is not None

    @property
    def module_name(self) -> str:
        return "objects"

    @property
    def required_quality(self) -> float:
        return 0.3

    @property
    def can_work_degraded(self) -> bool:
        return True

    @property
    def model_path(self) -> str:
        return self._model_path

    def _load_net(self) -> Optional[Any]:
        if self._net is not None:
            return self._net
        if self._load_attempted:
            return None
        self._load_attempted = True

        if cv2 is None:
            logger.warning("YOLO26 disabled: OpenCV is not installed")
            return None
        if not Path(self._model_path).is_file():
            logger.warning("YOLO26 disabled: model not found at %s", self._model_path)
            return None
        try:
            # Merely importing camera/percept types must not load this optional
            # runtime. It is needed only when an enabled detector has weights.
            import onnxruntime as ort

            options = ort.SessionOptions()
            options.intra_op_num_threads = self._intra_op_threads
            options.inter_op_num_threads = 1
            options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
            net = ort.InferenceSession(
                self._model_path,
                sess_options=options,
                providers=["CPUExecutionProvider"],
            )
            inputs = net.get_inputs()
            outputs = net.get_outputs()
            if not inputs or not outputs or outputs[0].shape[-1] != 6:
                raise ValueError("model is not an end-to-end YOLO26 detector")
            self._input_name = inputs[0].name
            self._net = net
            logger.info(
                "YOLO26 loaded through ONNX Runtime (%d threads): %s",
                self._intra_op_threads, self._model_path,
            )
            return net
        except ImportError:
            logger.warning("YOLO26 disabled: ONNX Runtime is not installed")
            return None
        except Exception:
            logger.exception("YOLO26 model load failed: %s", self._model_path)
            return None

    def analyze(self, frame: ProcessedFrame) -> Optional[ObjectOutput]:
        if frame.image is None or frame.image.size == 0 or cv2 is None:
            return None
        net = self._load_net()
        if net is None:
            return None

        t0 = time.monotonic()
        image = frame.image
        image_h, image_w = image.shape[:2]
        padded, scale, pad_x, pad_y = _letterbox(image, self._input_size)
        blob = cv2.dnn.blobFromImage(
            padded, scalefactor=1.0 / 255.0,
            size=(self._input_size, self._input_size),
            mean=(0, 0, 0), swapRB=True, crop=False,
        )
        if self._input_name is None:
            inputs = net.get_inputs()
            self._input_name = inputs[0].name
        raw = net.run(None, {self._input_name: blob})[0]
        detections = _decode_end2end(
            raw,
            confidence_threshold=self._confidence_threshold,
            labels=self._labels,
            scale=scale,
            pad_x=pad_x,
            pad_y=pad_y,
            image_width=image_w,
            image_height=image_h,
        )
        elapsed = (time.monotonic() - t0) * 1000.0
        confidence = max((item.confidence for item in detections), default=0.0)
        return ObjectOutput(
            module_name=self.module_name,
            confidence=confidence,
            is_degraded=frame.quality.overall < 0.5,
            processing_time_ms=elapsed,
            detections=detections,
            backend_used="yolo26-onnxruntime+opencv",
            image_size=(image_w, image_h),
        )


def _letterbox(image: np.ndarray, input_size: int) -> Tuple[np.ndarray, float, int, int]:
    """Resize preserving aspect ratio and pad to YOLO's square input."""
    if cv2 is None:
        raise RuntimeError("OpenCV is required for YOLO26 preprocessing")
    height, width = image.shape[:2]
    scale = min(input_size / width, input_size / height)
    resized_w = max(1, int(round(width * scale)))
    resized_h = max(1, int(round(height * scale)))
    resized = cv2.resize(image, (resized_w, resized_h), interpolation=cv2.INTER_LINEAR)
    pad_x = (input_size - resized_w) // 2
    pad_y = (input_size - resized_h) // 2
    padded = np.full((input_size, input_size, 3), 114, dtype=np.uint8)
    padded[pad_y:pad_y + resized_h, pad_x:pad_x + resized_w] = resized
    return padded, scale, pad_x, pad_y


def _decode_end2end(
    raw: Any,
    *,
    confidence_threshold: float,
    labels: Sequence[str],
    scale: float,
    pad_x: int,
    pad_y: int,
    image_width: int,
    image_height: int,
) -> List[ObjectDetection]:
    """Decode YOLO26's NMS-free ``(N, 300, 6)`` detection output."""
    if isinstance(raw, (list, tuple)):
        if not raw:
            return []
        raw = raw[0]
    rows = np.asarray(raw)
    if rows.ndim == 3:
        rows = rows[0]
    if rows.ndim != 2 or rows.shape[1] != 6:
        raise ValueError(f"Unexpected YOLO26 detection output shape: {rows.shape}")

    result = []
    for row in rows:
        confidence = float(row[4])
        if not np.isfinite(confidence) or confidence < confidence_threshold:
            continue
        class_id = int(round(float(row[5])))
        if class_id < 0 or class_id >= len(labels):
            continue
        x1 = int(round((float(row[0]) - pad_x) / scale))
        y1 = int(round((float(row[1]) - pad_y) / scale))
        x2 = int(round((float(row[2]) - pad_x) / scale))
        y2 = int(round((float(row[3]) - pad_y) / scale))
        x1 = min(max(x1, 0), max(0, image_width - 1))
        y1 = min(max(y1, 0), max(0, image_height - 1))
        x2 = min(max(x2, 0), max(0, image_width - 1))
        y2 = min(max(y2, 0), max(0, image_height - 1))
        if x2 <= x1 or y2 <= y1:
            continue
        result.append(ObjectDetection(
            class_id=class_id,
            label=str(labels[class_id]),
            confidence=confidence,
            bbox_xyxy=(x1, y1, x2, y2),
        ))
    result.sort(key=lambda item: item.confidence, reverse=True)
    return result
