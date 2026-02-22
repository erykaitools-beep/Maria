"""
Code Analyzer - READ-ONLY static analysis of Maria's codebase.

This module allows Maria to understand her own structure without
any ability to modify code. All operations are strictly read-only.

Security: This module NEVER writes, modifies, or executes code.
"""

import ast
import os
import json
import logging
from pathlib import Path
from typing import List, Dict, Optional, Set, Tuple
from datetime import datetime

from .code_model import (
    CodeModel, ModuleInfo, FunctionInfo, ClassInfo,
    CodeIssue, IssueType, IssueSeverity, DependencyEdge
)

logger = logging.getLogger(__name__)


class CodeAnalyzer:
    """
    Static analyzer for Maria's codebase.

    READ-ONLY: This class only reads files and builds a model.
    It cannot and will not modify any code.
    """

    # Directories to analyze (Maria's own code)
    MARIA_PACKAGES = [
        "agent_core",
        "maria_core",
        "maria_ui",
        "models",
    ]

    # Files to exclude
    EXCLUDE_PATTERNS = [
        "__pycache__",
        ".pyc",
        "test_",
        "_test.py",
        ".git",
        "venv",
        ".venv",
    ]

    # Maria's architectural layers (for classification)
    LAYER_MAPPING = {
        "core": ["agent_core/homeostasis", "agent_core/memory", "agent_core/llm"],
        "adapters": ["agent_core/adapters"],
        "legacy": ["maria_core"],
        "ui": ["maria_ui", "agent_core/ui"],
        "models": ["models"],
        "meta": ["agent_core/metacontrol", "agent_core/introspection"],
    }

    def __init__(self, project_root: str):
        """
        Initialize analyzer with project root path.

        Args:
            project_root: Absolute path to M.A.R.I.A. project root
        """
        self.project_root = Path(project_root)
        self._model: Optional[CodeModel] = None

    def analyze(self) -> CodeModel:
        """
        Perform full analysis of the codebase.

        Returns:
            CodeModel with complete self-representation

        Note: This is READ-ONLY - no files are modified.
        """
        logger.info(f"Starting code analysis of {self.project_root}")

        model = CodeModel(
            analysis_timestamp=datetime.now(),
            project_root=str(self.project_root)
        )

        # Find all Python files in Maria's packages
        python_files = self._find_python_files()
        logger.info(f"Found {len(python_files)} Python files to analyze")

        # Analyze each file
        for file_path in python_files:
            try:
                module_info = self._analyze_file(file_path)
                if module_info:
                    model.modules[module_info.package] = module_info
                    model.total_files += 1
                    model.total_lines += module_info.line_count
                    model.total_functions += module_info.function_count
                    model.total_classes += module_info.class_count
            except Exception as e:
                logger.warning(f"Failed to analyze {file_path}: {e}")

        # Build dependency graph
        model.dependencies = self._build_dependencies(model)

        # Classify into packages
        model.packages = self._classify_packages(model)

        # Classify into layers
        model.layers = self._classify_layers(model)

        # Find issues
        model.issues = self._find_issues(model)

        self._model = model
        logger.info(
            f"Analysis complete: {model.total_files} files, "
            f"{model.total_lines} lines, {len(model.issues)} issues"
        )

        return model

    def _find_python_files(self) -> List[Path]:
        """Find all Python files in Maria's packages (READ-ONLY)."""
        python_files = []

        for package in self.MARIA_PACKAGES:
            package_path = self.project_root / package
            if not package_path.exists():
                continue

            for py_file in package_path.rglob("*.py"):
                # Check exclusions
                path_str = str(py_file)
                if any(excl in path_str for excl in self.EXCLUDE_PATTERNS):
                    continue
                python_files.append(py_file)

        return sorted(python_files)

    def _analyze_file(self, file_path: Path) -> Optional[ModuleInfo]:
        """
        Analyze a single Python file (READ-ONLY).

        Args:
            file_path: Path to the Python file

        Returns:
            ModuleInfo or None if parsing fails
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                source = f.read()
        except Exception as e:
            logger.warning(f"Cannot read {file_path}: {e}")
            return None

        try:
            tree = ast.parse(source, filename=str(file_path))
        except SyntaxError as e:
            logger.warning(f"Syntax error in {file_path}: {e}")
            return None

        # Calculate relative path and package name
        rel_path = file_path.relative_to(self.project_root)
        package = str(rel_path).replace(os.sep, ".").replace(".py", "")
        if package.endswith(".__init__"):
            package = package[:-9]

        module = ModuleInfo(
            file_path=str(file_path),
            relative_path=str(rel_path),
            package=package,
            docstring=ast.get_docstring(tree),
            line_count=len(source.splitlines()),
        )

        # Extract information from AST
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    module.imports.append(alias.name)

            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    names = [alias.name for alias in node.names]
                    module.from_imports[node.module] = names

            elif isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef):
                func_info = self._extract_function_info(node, file_path)
                module.functions.append(func_info)

            elif isinstance(node, ast.ClassDef):
                class_info = self._extract_class_info(node, file_path)
                module.classes.append(class_info)

            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        module.global_variables.append(target.id)

        return module

    def _extract_function_info(
        self, node: ast.FunctionDef, file_path: Path
    ) -> FunctionInfo:
        """Extract information from a function definition (READ-ONLY)."""
        # Get parameters
        params = []
        for arg in node.args.args:
            params.append(arg.arg)

        # Check for type hints
        has_type_hints = (
            node.returns is not None or
            any(arg.annotation is not None for arg in node.args.args)
        )

        # Get decorators
        decorators = []
        for dec in node.decorator_list:
            if isinstance(dec, ast.Name):
                decorators.append(dec.id)
            elif isinstance(dec, ast.Attribute):
                decorators.append(dec.attr)

        return FunctionInfo(
            name=node.name,
            file_path=str(file_path),
            line_start=node.lineno,
            line_end=node.end_lineno or node.lineno,
            docstring=ast.get_docstring(node),
            parameters=params,
            has_type_hints=has_type_hints,
            is_async=isinstance(node, ast.AsyncFunctionDef),
            decorators=decorators,
        )

    def _extract_class_info(self, node: ast.ClassDef, file_path: Path) -> ClassInfo:
        """Extract information from a class definition (READ-ONLY)."""
        # Get base classes
        bases = []
        for base in node.bases:
            if isinstance(base, ast.Name):
                bases.append(base.id)
            elif isinstance(base, ast.Attribute):
                bases.append(base.attr)

        class_info = ClassInfo(
            name=node.name,
            file_path=str(file_path),
            line_start=node.lineno,
            line_end=node.end_lineno or node.lineno,
            docstring=ast.get_docstring(node),
            base_classes=bases,
        )

        # Extract methods
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                method = self._extract_function_info(item, file_path)
                class_info.methods.append(method)
            elif isinstance(item, ast.Assign):
                for target in item.targets:
                    if isinstance(target, ast.Name):
                        class_info.class_variables.append(target.id)

        return class_info

    def _build_dependencies(self, model: CodeModel) -> List[DependencyEdge]:
        """Build dependency graph between modules (READ-ONLY analysis)."""
        edges = []

        for package, module in model.modules.items():
            # Regular imports
            for imp in module.imports:
                edges.append(DependencyEdge(
                    from_module=package,
                    to_module=imp,
                    import_type="import",
                ))

            # From imports
            for from_module, names in module.from_imports.items():
                edges.append(DependencyEdge(
                    from_module=package,
                    to_module=from_module,
                    import_type="from",
                    imported_names=names,
                ))

        return edges

    def _classify_packages(self, model: CodeModel) -> Dict[str, List[str]]:
        """Classify modules into packages (READ-ONLY)."""
        packages: Dict[str, List[str]] = {}

        for package in model.modules.keys():
            parts = package.split(".")
            if parts:
                top_level = parts[0]
                if top_level not in packages:
                    packages[top_level] = []
                packages[top_level].append(package)

        return packages

    def _classify_layers(self, model: CodeModel) -> Dict[str, List[str]]:
        """Classify modules into architectural layers (READ-ONLY)."""
        layers: Dict[str, List[str]] = {layer: [] for layer in self.LAYER_MAPPING}

        for package in model.modules.keys():
            for layer, patterns in self.LAYER_MAPPING.items():
                for pattern in patterns:
                    if package.startswith(pattern.replace("/", ".")):
                        layers[layer].append(package)
                        break

        # Remove empty layers
        return {k: v for k, v in layers.items() if v}

    def _find_issues(self, model: CodeModel) -> List[CodeIssue]:
        """Find code issues in the codebase (READ-ONLY analysis)."""
        issues = []

        for package, module in model.modules.items():
            # Check for TODO/FIXME comments
            issues.extend(self._find_todo_fixme(module))

            # Check for missing docstrings
            issues.extend(self._find_missing_docstrings(module))

            # Check for long functions
            issues.extend(self._find_long_functions(module))

        return issues

    def _find_todo_fixme(self, module: ModuleInfo) -> List[CodeIssue]:
        """Find TODO and FIXME comments (READ-ONLY)."""
        issues = []

        try:
            with open(module.file_path, 'r', encoding='utf-8') as f:
                for line_num, line in enumerate(f, 1):
                    line_upper = line.upper()
                    if "TODO" in line_upper:
                        issues.append(CodeIssue(
                            issue_type=IssueType.TODO,
                            severity=IssueSeverity.INFO,
                            file_path=module.relative_path,
                            line_number=line_num,
                            message=line.strip()[:100],
                        ))
                    elif "FIXME" in line_upper:
                        issues.append(CodeIssue(
                            issue_type=IssueType.FIXME,
                            severity=IssueSeverity.WARNING,
                            file_path=module.relative_path,
                            line_number=line_num,
                            message=line.strip()[:100],
                        ))
        except Exception:
            pass

        return issues

    def _find_missing_docstrings(self, module: ModuleInfo) -> List[CodeIssue]:
        """Find functions/classes without docstrings (READ-ONLY)."""
        issues = []

        for func in module.functions:
            if not func.docstring and not func.name.startswith("_"):
                issues.append(CodeIssue(
                    issue_type=IssueType.MISSING_DOCSTRING,
                    severity=IssueSeverity.INFO,
                    file_path=module.relative_path,
                    line_number=func.line_start,
                    message=f"Function '{func.name}' has no docstring",
                ))

        for cls in module.classes:
            if not cls.docstring:
                issues.append(CodeIssue(
                    issue_type=IssueType.MISSING_DOCSTRING,
                    severity=IssueSeverity.INFO,
                    file_path=module.relative_path,
                    line_number=cls.line_start,
                    message=f"Class '{cls.name}' has no docstring",
                ))

        return issues

    def _find_long_functions(self, module: ModuleInfo) -> List[CodeIssue]:
        """Find functions that are too long (READ-ONLY)."""
        issues = []
        max_lines = 50

        for func in module.functions:
            if func.line_count > max_lines:
                issues.append(CodeIssue(
                    issue_type=IssueType.LONG_FUNCTION,
                    severity=IssueSeverity.WARNING,
                    file_path=module.relative_path,
                    line_number=func.line_start,
                    message=f"Function '{func.name}' has {func.line_count} lines (>{max_lines})",
                ))

        return issues

    def save_model(self, output_path: str) -> None:
        """
        Save the code model to a JSON file.

        Args:
            output_path: Path to save the model
        """
        if not self._model:
            raise ValueError("No model to save. Run analyze() first.")

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(self._model.to_dict(), f, indent=2, ensure_ascii=False)

        logger.info(f"Code model saved to {output_path}")

    @staticmethod
    def load_model(input_path: str) -> CodeModel:
        """
        Load a previously saved code model.

        Args:
            input_path: Path to the saved model

        Returns:
            CodeModel reconstructed from JSON
        """
        with open(input_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        return CodeModel.from_dict(data)

    def get_model(self) -> Optional[CodeModel]:
        """Get the current model (after analyze())."""
        return self._model
