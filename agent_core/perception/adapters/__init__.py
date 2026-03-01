"""
Perception Adapters - mapowanie istniejacych strumieni danych na PerceptionEvent.

Kazdy adapter ma metode to_perception_event() (lub wiele metod per event_type)
ktora konwertuje istniejace dataclasses/dicts na wspolny format PerceptionEvent.

Kontrakt: docs/CONTRACTS.md - Kontrakt 1, sekcja "Adaptery"
"""

from agent_core.perception.adapters.sensor_adapter import SensorAdapter
from agent_core.perception.adapters.user_adapter import UserAdapter
from agent_core.perception.adapters.learning_adapter import LearningAdapter
from agent_core.perception.adapters.exam_adapter import ExamAdapter
from agent_core.perception.adapters.consciousness_adapter import ConsciousnessAdapter
from agent_core.perception.adapters.teacher_adapter import TeacherAdapter

__all__ = [
    "SensorAdapter",
    "UserAdapter",
    "LearningAdapter",
    "ExamAdapter",
    "ConsciousnessAdapter",
    "TeacherAdapter",
]
