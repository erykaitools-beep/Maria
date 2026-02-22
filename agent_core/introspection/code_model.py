"""
Data structures for Maria's code self-model.

These represent Maria's understanding of her own architecture.
All data is derived from static analysis - no runtime introspection.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Set
from datetime import datetime
from enum import Enum


class IssueType(Enum):
    """Types of code issues Maria can detect in herself."""
    TODO = "todo"
    FIXME = "fixme"
    UNUSED_IMPORT = "unused_import"
    MISSING_DOCSTRING = "missing_docstring"
    MISSING_TYPE_HINT = "missing_type_hint"
    CIRCULAR_IMPORT = "circular_import"
    LONG_FUNCTION = "long_function"  # > 50 lines
    COMPLEX_FUNCTION = "complex_function"  # high cyclomatic complexity


class IssueSeverity(Enum):
    """Severity levels for issues."""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass
class CodeIssue:
    """An issue Maria found in her own code."""
    issue_type: IssueType
    severity: IssueSeverity
    file_path: str
    line_number: Optional[int]
    message: str

    def to_dict(self) -> dict:
        return {
            "type": self.issue_type.value,
            "severity": self.severity.value,
            "file": self.file_path,
            "line": self.line_number,
            "message": self.message,
        }


@dataclass
class FunctionInfo:
    """Information about a function/method."""
    name: str
    file_path: str
    line_start: int
    line_end: int
    docstring: Optional[str]
    parameters: List[str]
    has_type_hints: bool
    is_async: bool
    decorators: List[str] = field(default_factory=list)
    calls: List[str] = field(default_factory=list)  # Functions this calls

    @property
    def line_count(self) -> int:
        return self.line_end - self.line_start + 1

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "file": self.file_path,
            "lines": f"{self.line_start}-{self.line_end}",
            "line_count": self.line_count,
            "has_docstring": self.docstring is not None,
            "has_type_hints": self.has_type_hints,
            "is_async": self.is_async,
            "parameters": self.parameters,
            "decorators": self.decorators,
        }


@dataclass
class ClassInfo:
    """Information about a class."""
    name: str
    file_path: str
    line_start: int
    line_end: int
    docstring: Optional[str]
    base_classes: List[str]
    methods: List[FunctionInfo] = field(default_factory=list)
    class_variables: List[str] = field(default_factory=list)

    @property
    def method_count(self) -> int:
        return len(self.methods)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "file": self.file_path,
            "lines": f"{self.line_start}-{self.line_end}",
            "has_docstring": self.docstring is not None,
            "base_classes": self.base_classes,
            "method_count": self.method_count,
            "methods": [m.name for m in self.methods],
        }


@dataclass
class ModuleInfo:
    """Information about a Python module (file)."""
    file_path: str
    relative_path: str  # Relative to project root
    package: str  # e.g., "agent_core.homeostasis"
    docstring: Optional[str]
    imports: List[str] = field(default_factory=list)
    from_imports: Dict[str, List[str]] = field(default_factory=dict)
    functions: List[FunctionInfo] = field(default_factory=list)
    classes: List[ClassInfo] = field(default_factory=list)
    global_variables: List[str] = field(default_factory=list)
    line_count: int = 0

    @property
    def function_count(self) -> int:
        return len(self.functions)

    @property
    def class_count(self) -> int:
        return len(self.classes)

    def to_dict(self) -> dict:
        return {
            "file": self.relative_path,
            "package": self.package,
            "has_docstring": self.docstring is not None,
            "line_count": self.line_count,
            "imports": self.imports,
            "function_count": self.function_count,
            "class_count": self.class_count,
            "functions": [f.name for f in self.functions],
            "classes": [c.name for c in self.classes],
        }


@dataclass
class DependencyEdge:
    """A dependency between two modules."""
    from_module: str
    to_module: str
    import_type: str  # "import" or "from"
    imported_names: List[str] = field(default_factory=list)


@dataclass
class CodeModel:
    """
    Maria's complete self-model of her codebase.

    This is what Maria "knows" about her own architecture.
    Updated periodically by CodeAnalyzer.
    """
    # Metadata
    analysis_timestamp: datetime = field(default_factory=datetime.now)
    project_root: str = ""

    # Statistics
    total_files: int = 0
    total_lines: int = 0
    total_functions: int = 0
    total_classes: int = 0

    # Detailed info
    modules: Dict[str, ModuleInfo] = field(default_factory=dict)

    # Dependency graph
    dependencies: List[DependencyEdge] = field(default_factory=list)

    # Issues found
    issues: List[CodeIssue] = field(default_factory=list)

    # Package structure
    packages: Dict[str, List[str]] = field(default_factory=dict)  # package -> modules

    # Layer classification
    layers: Dict[str, List[str]] = field(default_factory=dict)  # layer -> modules

    def get_statistics(self) -> dict:
        """Get summary statistics about the codebase."""
        return {
            "timestamp": self.analysis_timestamp.isoformat(),
            "files": self.total_files,
            "lines": self.total_lines,
            "functions": self.total_functions,
            "classes": self.total_classes,
            "packages": len(self.packages),
            "issues": {
                "total": len(self.issues),
                "by_type": self._count_issues_by_type(),
                "by_severity": self._count_issues_by_severity(),
            },
        }

    def _count_issues_by_type(self) -> Dict[str, int]:
        counts = {}
        for issue in self.issues:
            key = issue.issue_type.value
            counts[key] = counts.get(key, 0) + 1
        return counts

    def _count_issues_by_severity(self) -> Dict[str, int]:
        counts = {}
        for issue in self.issues:
            key = issue.severity.value
            counts[key] = counts.get(key, 0) + 1
        return counts

    def get_module(self, name: str) -> Optional[ModuleInfo]:
        """Get module info by package name or path."""
        return self.modules.get(name)

    def get_layer_modules(self, layer: str) -> List[str]:
        """Get all modules in a given layer."""
        return self.layers.get(layer, [])

    def to_dict(self) -> dict:
        """Convert entire model to dictionary for JSON serialization."""
        return {
            "metadata": {
                "timestamp": self.analysis_timestamp.isoformat(),
                "project_root": self.project_root,
            },
            "statistics": self.get_statistics(),
            "packages": self.packages,
            "layers": self.layers,
            "modules": {k: v.to_dict() for k, v in self.modules.items()},
            "issues": [i.to_dict() for i in self.issues],
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'CodeModel':
        """Reconstruct CodeModel from dictionary (for loading from JSON)."""
        model = cls()
        model.analysis_timestamp = datetime.fromisoformat(
            data.get("metadata", {}).get("timestamp", datetime.now().isoformat())
        )
        model.project_root = data.get("metadata", {}).get("project_root", "")

        stats = data.get("statistics", {})
        model.total_files = stats.get("files", 0)
        model.total_lines = stats.get("lines", 0)
        model.total_functions = stats.get("functions", 0)
        model.total_classes = stats.get("classes", 0)

        model.packages = data.get("packages", {})
        model.layers = data.get("layers", {})

        # Note: Full reconstruction of modules/issues would need more work
        # For now, this gives basic stats access after loading

        return model
