"""
VisionCortex - central integrator for visual perception.

Coordinates sensors, preprocessing, and analysis modules into
a single perceive() call that produces a VisionPercept.

Pipeline per tick:
1. Select best sensor
2. Capture frame
3. Preprocess (normalize + quality + degradation)
4. Run modules adaptively (based on quality)
5. Generate summary
6. Return VisionPercept

Phase 4: Vision Cortex (VISION_SPEC.md)
"""

import logging
import threading
import time
from dataclasses import replace
from typing import Any, Callable, Dict, List, Optional

from agent_core.llm.work_priority import WorkPurpose, work_purpose

from agent_core.vision.models import VisionMode
from agent_core.vision.modules.base import ModuleOutput, VisionModule
from agent_core.vision.modules.motion.detector import MotionModule, MotionOutput
from agent_core.vision.modules.objects.detector import ObjectOutput
from agent_core.vision.modules.scene.analyzer import SceneModule, SceneOutput
from agent_core.vision.percept import VisionPercept, generate_summary
from agent_core.vision.preprocessing.preprocessor import ProcessedFrame, VisionPreprocessor
from agent_core.vision.sensors.base import VisionSensor
from agent_core.vision.sensors.health import SensorHealth

logger = logging.getLogger(__name__)

# Quality thresholds for running modules
_QUALITY_FOR_SCENE = 0.3
_QUALITY_FOR_MOTION = 0.2
_QUALITY_FOR_OBJECTS = 0.3


class VisionCortex:
    """Central integrator for all visual perception.

    Manages sensors, preprocessing, and modules. A single perceive()
    call runs the full pipeline and returns a unified VisionPercept.

    Usage:
        cortex = VisionCortex()
        cortex.add_sensor(usb_sensor)
        cortex.add_module(MotionModule())
        cortex.add_module(SceneModule())

        percept = cortex.perceive()
        if percept:
            print(percept.summary)
    """

    def __init__(
        self,
        preprocessor: Optional[VisionPreprocessor] = None,
    ):
        self._sensors: Dict[str, VisionSensor] = {}
        self._modules: Dict[str, VisionModule] = {}
        self._preprocessor = preprocessor or VisionPreprocessor()
        self._active_sensor_id: Optional[str] = None
        self._last_percept: Optional[VisionPercept] = None
        self._last_frame_image: Optional[Any] = None  # np.ndarray from last capture
        self._last_processed_frame: Optional[ProcessedFrame] = None
        self._capture_lock = threading.RLock()

    def add_sensor(self, sensor: VisionSensor) -> None:
        """Register a sensor."""
        self._sensors[sensor.sensor_id] = sensor

    def remove_sensor(self, sensor_id: str) -> None:
        """Remove a sensor."""
        self._sensors.pop(sensor_id, None)
        if self._active_sensor_id == sensor_id:
            self._active_sensor_id = None

    def add_module(self, module: VisionModule) -> None:
        """Register an analysis module."""
        self._modules[module.module_name] = module

    def remove_module(self, module_name: str) -> None:
        """Remove an analysis module."""
        self._modules.pop(module_name, None)

    @property
    def active_sensor(self) -> Optional[VisionSensor]:
        """Currently active sensor (best available)."""
        if self._active_sensor_id and self._active_sensor_id in self._sensors:
            return self._sensors[self._active_sensor_id]
        return None

    @property
    def last_percept(self) -> Optional[VisionPercept]:
        """Last perception result."""
        return self._last_percept

    @property
    def sensor_count(self) -> int:
        return len(self._sensors)

    @property
    def module_count(self) -> int:
        return len(self._modules)

    def perceive(self) -> Optional[VisionPercept]:
        # Serialize camera/preprocessor and stateful local modules. Never hold
        # this lock while waiting for an on-demand VLM description.
        with self._capture_lock:
            return self._perceive_local()

    def _perceive_local(self) -> Optional[VisionPercept]:
        """Run the full visual perception pipeline.

        Returns None only if no sensor is available.
        Returns degraded VisionPercept if sensor has issues.
        """
        t0 = time.monotonic()
        self._last_processed_frame = None
        self._last_frame_image = None

        # 1. Select best sensor
        sensor = self._select_best_sensor()
        if sensor is None:
            self._last_percept = self._make_blind_percept()
            return self._last_percept

        self._active_sensor_id = sensor.sensor_id

        # 2. Capture frame
        frame = sensor.capture_frame()
        if frame is None:
            health = sensor.health
            self._last_percept = VisionPercept(
                vision_health=health,
                quality=0.0,
                summary=health.to_human_description(),
                sensor_id=sensor.sensor_id,
                total_processing_time_ms=(time.monotonic() - t0) * 1000.0,
            )
            return self._last_percept

        # 3. Preprocess
        processed = self._preprocessor.process(frame)

        # 4. Run modules adaptively
        motion_output = None
        objects_output = None
        scene_output = None
        modules_run = []

        quality = processed.quality.overall

        # Motion module (lowest quality requirement)
        if "motion" in self._modules and quality >= _QUALITY_FOR_MOTION:
            motion_output = self._run_module("motion", processed)
            if motion_output is not None:
                modules_run.append("motion")

        # Fast local object detector. This provides concrete semantics in the
        # tick without waking the slow VLM and is inert unless registered.
        if "objects" in self._modules and quality >= _QUALITY_FOR_OBJECTS:
            objects_output = self._run_module("objects", processed)
            if objects_output is not None:
                modules_run.append("objects")

        # Scene module
        if "scene" in self._modules and quality >= _QUALITY_FOR_SCENE:
            scene_output = self._run_module("scene", processed)
            if scene_output is not None:
                modules_run.append("scene")

        # 5. Generate summary
        health = sensor.health
        summary = generate_summary(
            health=health,
            quality=quality,
            motion=motion_output if isinstance(motion_output, MotionOutput) else None,
            scene=scene_output if isinstance(scene_output, SceneOutput) else None,
            objects=objects_output if isinstance(objects_output, ObjectOutput) else None,
        )

        elapsed = (time.monotonic() - t0) * 1000.0

        percept = VisionPercept(
            vision_health=health,
            vision_mode=frame.mode,
            quality=quality,
            motion=motion_output if isinstance(motion_output, MotionOutput) else None,
            objects=objects_output if isinstance(objects_output, ObjectOutput) else None,
            scene=scene_output if isinstance(scene_output, SceneOutput) else None,
            summary=summary,
            total_processing_time_ms=elapsed,
            modules_run=modules_run,
            sensor_id=sensor.sensor_id,
        )

        self._last_percept = percept
        self._last_frame_image = processed.image
        self._last_processed_frame = processed
        return percept

    def open_all_sensors(self) -> int:
        """Open all registered sensors. Returns count of successfully opened."""
        opened = 0
        for sensor in self._sensors.values():
            try:
                if sensor.open():
                    opened += 1
            except Exception:
                logger.exception("Failed to open sensor %s", sensor.sensor_id)
        return opened

    def close_all_sensors(self) -> None:
        """Close all registered sensors."""
        for sensor in self._sensors.values():
            try:
                sensor.close()
            except Exception:
                logger.exception("Failed to close sensor %s", sensor.sensor_id)
        self._active_sensor_id = None

    def describe_scene_llava(self) -> Optional[str]:
        """Describe a fresh snapshot without modifying the tick's module."""
        return self.describe_snapshot()

    def perceive_snapshot(self) -> Optional[VisionPercept]:
        """Detailed manual perception of one frame, isolated from tick state."""
        return self.perceive_snapshot_with_frame()[0]

    @work_purpose(WorkPurpose.ACTION)
    def perceive_snapshot_with_frame(self):
        """Return the manual percept and its exact image, even as ticks continue."""
        with self._capture_lock:
            percept = self.perceive()
            processed = self._last_processed_frame
            image = self._last_frame_image.copy() if self._last_frame_image is not None else None
            if processed is not None and image is not None:
                processed = replace(processed, image=image)
        scene_mod = self._modules.get("scene")
        fn = getattr(scene_mod, "_llava_describe", None)
        if (percept is None or processed is None or fn is None
                or not isinstance(scene_mod, SceneModule)
                or processed.quality.overall < _QUALITY_FOR_SCENE):
            return percept, image
        private_scene = SceneModule(llava_fn=fn)
        private_scene._prompt = scene_mod._prompt
        result = private_scene.analyze(processed)
        if result is None:
            return percept, image
        return replace(percept, scene=result, summary=generate_summary(
            health=percept.vision_health, quality=percept.quality,
            motion=percept.motion, objects=percept.objects, scene=result,
        ), total_processing_time_ms=(
            percept.total_processing_time_ms + result.processing_time_ms
        )), image

    def preview_snapshot(self):
        """Copy one consistent live percept/frame for the off-tick publisher."""
        from agent_core.vision.preview import percept_state
        with self._capture_lock:
            percept = self._last_percept
            if percept is None:
                return None, None
            state = {"status": self.get_status(), "last_percept": percept_state(percept)}
            sensor = self.active_sensor
            if sensor is not None:
                state["health"] = {"sensor_id": sensor.sensor_id,
                                   "health": sensor.health.to_dict(),
                                   "description": sensor.health.to_human_description()}
            image = self._last_frame_image.copy() if self._last_frame_image is not None else None
            return state, image

    @work_purpose(WorkPurpose.ACTION)
    def describe_snapshot(
        self,
        prompt: Optional[str] = None,
        save_path: Optional[str] = None,
        frame_gate: Optional[Callable[[str], bool]] = None,
    ) -> Optional[str]:
        """Thread-safe one-shot LLaVA scene description for the autonomous path.

        Camera capture is serialized with regular perception; the slow call
        runs after releasing that lock and never changes the shared module.

        Args:
            prompt: override prompt for LLaVA (defaults to the SceneModule's
                structured prompt). VisionAdvisor passes a short natural-language
                prompt for a clean one-sentence ping.
            save_path: if set, the exact frame LLaVA looked at is written there
                (JPEG) so the operator can be sent the image alongside the
                description. Written BEFORE the describe, because frame_gate
                needs a file to look at; the advisor only sends the image when
                a description came back, so an early write changes nothing the
                operator sees.
            frame_gate: optional veto called with save_path just before the
                expensive call. Returning False skips the describe entirely --
                that is the whole point, the ~30-120s is what we are trying not
                to spend. Requires save_path; without one there is no frame to
                judge and the gate is ignored.
        """
        scene_mod = self._modules.get("scene")
        if not isinstance(scene_mod, SceneModule):
            return None
        llava_fn = getattr(scene_mod, "_llava_describe", None) or getattr(
            scene_mod, "_llava_fn", None
        )
        prompt_to_use = prompt or getattr(scene_mod, "_prompt", None)
        if llava_fn is None or prompt_to_use is None:
            return None

        with self._capture_lock:
            sensor = self._select_best_sensor()
            if sensor is None:
                return None
            frame = sensor.capture_frame()
            if frame is None:
                return None
            processed = self._preprocessor.process(frame)
        if processed.quality.overall < _QUALITY_FOR_SCENE:
            return None

        try:
            from agent_core.vision.modules.scene.analyzer import _image_to_base64
            b64 = _image_to_base64(processed.image)

            saved = False
            if save_path:
                try:
                    import base64 as _b64
                    with open(save_path, "wb") as f:
                        f.write(_b64.b64decode(b64))
                    saved = True
                except Exception as e:
                    logger.warning(f"describe_snapshot frame save failed: {e}")

            if frame_gate is not None and saved:
                try:
                    if not frame_gate(save_path):
                        logger.info("describe_snapshot: frame_gate odrzucil klatke "
                                    "-- pomijam drogi opis")
                        return None
                except Exception as e:
                    # Fail-open: a broken gate must not blind the advisor.
                    logger.warning(f"describe_snapshot frame_gate failed: {e}")

            result = llava_fn(prompt_to_use, b64)
            if not result or not result.strip():
                return None
            return result.strip()
        except Exception as e:
            logger.warning(f"describe_snapshot LLaVA call failed: {e}")
            return None

    def save_last_frame(self, save_path: str, *, image=None) -> bool:
        """Save the exact most recent processed frame without another capture.

        Used by the YOLO26 advisor path: the event and photo stay bound to the
        same perception, and no VLM call is needed just to create a snapshot.
        """
        source = self._last_frame_image if image is None else image
        if source is None:
            return False
        try:
            from pathlib import Path
            import cv2

            target = Path(save_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            image = source.copy()
            return bool(cv2.imwrite(str(target), image))
        except Exception as e:
            logger.warning("save_last_frame failed: %s", e)
            return False

    def reset(self) -> None:
        """Reset internal state (preprocessor + modules)."""
        self._preprocessor.reset()
        for module in self._modules.values():
            if hasattr(module, "reset"):
                module.reset()
        self._last_percept = None

    def get_status(self) -> dict:
        """Status summary for Web UI / Telegram."""
        sensor_status = {}
        for sid, sensor in self._sensors.items():
            sensor_status[sid] = {
                "is_open": sensor.is_open,
                "health": sensor.health.overall,
                "active": sid == self._active_sensor_id,
            }

        return {
            "sensors": sensor_status,
            "modules": list(self._modules.keys()),
            "active_sensor": self._active_sensor_id,
            "last_percept_quality": (
                round(self._last_percept.quality, 3) if self._last_percept else None
            ),
        }

    def _select_best_sensor(self) -> Optional[VisionSensor]:
        """Select the best available sensor by health score."""
        if not self._sensors:
            return None

        best = None
        best_health = -1.0

        for sensor in self._sensors.values():
            if not sensor.is_open:
                continue
            h = sensor.health.overall
            if h > best_health:
                best = sensor
                best_health = h

        return best

    def _run_module(self, name: str, frame: ProcessedFrame) -> Optional[ModuleOutput]:
        """Run a module safely, catching exceptions."""
        module = self._modules.get(name)
        if module is None:
            return None

        try:
            return module.analyze(frame)
        except Exception:
            logger.exception("Module %s failed", name)
            return None

    def _make_blind_percept(self) -> VisionPercept:
        """Percept when no sensor is available."""
        health = SensorHealth.disconnected()
        return VisionPercept(
            vision_health=health,
            quality=0.0,
            summary=health.to_human_description(),
        )
