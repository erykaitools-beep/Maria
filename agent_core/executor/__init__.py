"""
Executor Module - Module signal dispatch

Components:
- module_executor.py: ModuleExecutor for inter-module communication

Spec reference: homeostasis_spec.md lines 1729-1753
"""

from .module_executor import ModuleExecutor

__all__ = [
    "ModuleExecutor",
]
