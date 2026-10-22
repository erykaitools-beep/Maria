"""Fast local object detection backends."""

from agent_core.vision.modules.objects.detector import (
    ObjectDetection,
    ObjectOutput,
    YOLO26ObjectModule,
)

__all__ = ["ObjectDetection", "ObjectOutput", "YOLO26ObjectModule"]
