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
import time
from typing import Dict, List, Optional

from agent_core.vision.models import VisionMode
from agent_core.vision.modules.base import ModuleOutput, VisionModule
from agent_core.vision.modules.motion.detector import MotionModule, MotionOutput
from agent_core.vision.modules.scene.analyzer import SceneModule, SceneOutput
from agent_core.vision.percept import VisionPercept, generate_summary
from agent_core.vision.preprocessing.preprocessor import ProcessedFrame, VisionPreprocessor
from agent_core.vision.sensors.base import VisionSensor
from agent_core.vision.sensors.health import SensorHealth

logger = logging.getLogger(__name__)

# Quality thresholds for running modules
_QUALITY_FOR_SCENE = 0.3
_QUALITY_FOR_MOTION = 0.2


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
        """Run the full visual perception pipeline.

        Returns None only if no sensor is available.
        Returns degraded VisionPercept if sensor has issues.
        """
        t0 = time.monotonic()

        # 1. Select best sensor
        sensor = self._select_best_sensor()
        if sensor is None:
            return self._make_blind_percept()

        self._active_sensor_id = sensor.sensor_id

        # 2. Capture frame
        frame = sensor.capture_frame()
        if frame is None:
            health = sensor.health
            return VisionPercept(
                vision_health=health,
                quality=0.0,
                summary=health.to_human_description(),
                sensor_id=sensor.sensor_id,
                total_processing_time_ms=(time.monotonic() - t0) * 1000.0,
            )

        # 3. Preprocess
        processed = self._preprocessor.process(frame)

        # 4. Run modules adaptively
        motion_output = None
        scene_output = None
        modules_run = []

        quality = processed.quality.overall

        # Motion module (lowest quality requirement)
        if "motion" in self._modules and quality >= _QUALITY_FOR_MOTION:
            motion_output = self._run_module("motion", processed)
            if motion_output is not None:
                modules_run.append("motion")

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
        )

        elapsed = (time.monotonic() - t0) * 1000.0

        percept = VisionPercept(
            vision_health=health,
            vision_mode=frame.mode,
            quality=quality,
            motion=motion_output if isinstance(motion_output, MotionOutput) else None,
            scene=scene_output if isinstance(scene_output, SceneOutput) else None,
            summary=summary,
            total_processing_time_ms=elapsed,
            modules_run=modules_run,
            sensor_id=sensor.sensor_id,
        )

        self._last_percept = percept
        self._last_frame_image = processed.image
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
        """On-demand scene description using LLaVA (~30s).

        Temporarily enables LLaVA on SceneModule, captures a fresh frame,
        and returns the description. Used for chat queries ("co widzisz?"),
        not in the tick loop.
        """
        scene_mod = self._modules.get("scene")
        if not isinstance(scene_mod, SceneModule):
            return None

        llava_fn = getattr(scene_mod, '_llava_describe', None)
        if llava_fn is None:
            return None

        sensor = self._select_best_sensor()
        if sensor is None:
            return None

        frame = sensor.capture_frame()
        if frame is None:
            return None

        processed = self._preprocessor.process(frame)
        if processed.quality.overall < _QUALITY_FOR_SCENE:
            return None

        # Temporarily enable LLaVA for this one call
        old_fn = scene_mod._llava_fn
        scene_mod._llava_fn = llava_fn
        try:
            result = scene_mod.analyze(processed)
            if result and result.backend_used == "llava":
                return result.description
        finally:
            scene_mod._llava_fn = old_fn

        return None

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
