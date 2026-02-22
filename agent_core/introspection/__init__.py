"""
M.A.R.I.A. Code Introspection Module

Self-awareness of own code structure. READ-ONLY analysis.
Maria knows how she is built without modifying herself.

Components:
- CodeModel: Data structures for self-representation
- CodeAnalyzer: Static analysis of codebase (read-only)
- Reporter: Human/technical output formatting
- Scheduler: Periodic analysis integrated with homeostasis
"""

from .code_model import CodeModel, ModuleInfo, FunctionInfo, ClassInfo
from .analyzer import CodeAnalyzer
from .reporters import HumanReporter, TechnicalReporter, DualReporter
from .scheduler import (
    IntrospectionScheduler,
    get_introspection_scheduler,
    init_introspection,
)

__all__ = [
    'CodeModel',
    'ModuleInfo',
    'FunctionInfo',
    'ClassInfo',
    'CodeAnalyzer',
    'HumanReporter',
    'TechnicalReporter',
    'DualReporter',
    'IntrospectionScheduler',
    'get_introspection_scheduler',
    'init_introspection',
]
