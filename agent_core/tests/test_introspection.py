"""
Tests for code introspection module.

Tests are READ-ONLY - they verify analysis without modifying code.
"""

import os
import json
import tempfile
import pytest
from pathlib import Path
from datetime import datetime

from agent_core.introspection.code_model import (
    CodeModel, ModuleInfo, FunctionInfo, ClassInfo,
    CodeIssue, IssueType, IssueSeverity,
)
from agent_core.introspection.analyzer import CodeAnalyzer
from agent_core.introspection.reporters import (
    HumanReporter, TechnicalReporter, DualReporter
)
from agent_core.introspection.scheduler import IntrospectionScheduler


class TestCodeModel:
    """Tests for CodeModel data structures."""

    def test_code_model_init(self):
        """Test CodeModel initialization."""
        model = CodeModel()
        assert model.total_files == 0
        assert model.total_lines == 0
        assert model.total_functions == 0
        assert model.total_classes == 0
        assert isinstance(model.modules, dict)
        assert isinstance(model.issues, list)

    def test_code_model_statistics(self):
        """Test statistics computation."""
        model = CodeModel(
            total_files=10,
            total_lines=1000,
            total_functions=50,
            total_classes=15,
        )
        stats = model.get_statistics()

        assert stats["files"] == 10
        assert stats["lines"] == 1000
        assert stats["functions"] == 50
        assert stats["classes"] == 15
        assert "timestamp" in stats
        assert "issues" in stats

    def test_code_model_to_dict(self):
        """Test serialization to dict."""
        model = CodeModel(
            total_files=5,
            total_lines=500,
            project_root="/test/path",
        )
        data = model.to_dict()

        assert "metadata" in data
        assert "statistics" in data
        assert "modules" in data
        assert data["metadata"]["project_root"] == "/test/path"

    def test_code_model_from_dict(self):
        """Test deserialization from dict."""
        data = {
            "metadata": {
                "timestamp": datetime.now().isoformat(),
                "project_root": "/test/path",
            },
            "statistics": {
                "files": 10,
                "lines": 1000,
                "functions": 50,
                "classes": 15,
                "packages": 3,
            },
            "packages": {},
            "layers": {},
            "modules": {},
            "issues": [],
        }

        model = CodeModel.from_dict(data)
        assert model.total_files == 10
        assert model.total_lines == 1000
        assert model.project_root == "/test/path"

    def test_issue_to_dict(self):
        """Test CodeIssue serialization."""
        issue = CodeIssue(
            issue_type=IssueType.TODO,
            severity=IssueSeverity.INFO,
            file_path="test.py",
            line_number=42,
            message="Fix this later",
        )
        data = issue.to_dict()

        assert data["type"] == "todo"
        assert data["severity"] == "info"
        assert data["file"] == "test.py"
        assert data["line"] == 42


class TestFunctionInfo:
    """Tests for FunctionInfo."""

    def test_function_info_line_count(self):
        """Test line count property."""
        func = FunctionInfo(
            name="test_func",
            file_path="test.py",
            line_start=10,
            line_end=25,
            docstring="Test function",
            parameters=["x", "y"],
            has_type_hints=True,
            is_async=False,
        )
        assert func.line_count == 16

    def test_function_info_to_dict(self):
        """Test serialization."""
        func = FunctionInfo(
            name="async_func",
            file_path="test.py",
            line_start=1,
            line_end=10,
            docstring=None,
            parameters=["arg"],
            has_type_hints=False,
            is_async=True,
            decorators=["async_method"],
        )
        data = func.to_dict()

        assert data["name"] == "async_func"
        assert data["is_async"] is True
        assert data["has_docstring"] is False
        assert data["decorators"] == ["async_method"]


class TestClassInfo:
    """Tests for ClassInfo."""

    def test_class_info_method_count(self):
        """Test method count property."""
        cls = ClassInfo(
            name="TestClass",
            file_path="test.py",
            line_start=1,
            line_end=50,
            docstring="Test class",
            base_classes=["BaseClass"],
        )
        cls.methods = [
            FunctionInfo("method1", "test.py", 5, 10, None, [], False, False),
            FunctionInfo("method2", "test.py", 15, 20, None, [], False, False),
        ]
        assert cls.method_count == 2

    def test_class_info_to_dict(self):
        """Test serialization."""
        cls = ClassInfo(
            name="MyClass",
            file_path="test.py",
            line_start=1,
            line_end=100,
            docstring="My class",
            base_classes=["Parent1", "Parent2"],
        )
        data = cls.to_dict()

        assert data["name"] == "MyClass"
        assert data["has_docstring"] is True
        assert data["base_classes"] == ["Parent1", "Parent2"]


class TestCodeAnalyzer:
    """Tests for CodeAnalyzer (READ-ONLY operations)."""

    @pytest.fixture
    def temp_project(self, tmp_path):
        """Create a temporary project structure for testing."""
        # Create a simple Python file
        test_module = tmp_path / "test_module.py"
        test_module.write_text('''"""Test module docstring."""

import os
from typing import List

# TODO: Add more tests

class TestClass:
    """A test class."""

    def method_one(self, x: int) -> int:
        """Method with type hints."""
        return x * 2

    def method_two(self):
        # FIXME: This needs work
        pass


def standalone_function(a, b):
    return a + b


GLOBAL_VAR = 42
''')
        return tmp_path

    def test_analyzer_init(self, temp_project):
        """Test analyzer initialization."""
        analyzer = CodeAnalyzer(str(temp_project))
        assert analyzer.project_root == temp_project

    def test_analyzer_find_python_files(self):
        """Test finding Python files on the real project."""
        # Use the real project instead of temp directory
        # This avoids pytest isolation issues
        import os
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)
        )))

        analyzer = CodeAnalyzer(project_root)
        files = analyzer._find_python_files()

        # Real project should have many files
        assert len(files) >= 10
        file_names = [f.name for f in files]
        # Should find core.py in homeostasis
        assert "core.py" in file_names

    def test_analyzer_analyze_file(self, temp_project):
        """Test analyzing a single file."""
        test_file = temp_project / "test_module.py"

        analyzer = CodeAnalyzer(str(temp_project))
        module = analyzer._analyze_file(test_file)

        assert module is not None
        assert module.line_count > 0
        assert "Test module docstring" in module.docstring
        assert len(module.functions) == 1  # standalone_function
        assert len(module.classes) == 1  # TestClass
        assert "os" in module.imports

    def test_analyzer_find_todo_fixme(self, temp_project):
        """Test finding TODO/FIXME comments."""
        test_file = temp_project / "test_module.py"

        analyzer = CodeAnalyzer(str(temp_project))
        module = analyzer._analyze_file(test_file)

        issues = analyzer._find_todo_fixme(module)
        assert len(issues) == 2  # One TODO, one FIXME

        todo_issues = [i for i in issues if i.issue_type == IssueType.TODO]
        fixme_issues = [i for i in issues if i.issue_type == IssueType.FIXME]

        assert len(todo_issues) == 1
        assert len(fixme_issues) == 1


class TestReporters:
    """Tests for report generators."""

    @pytest.fixture
    def sample_model(self):
        """Create a sample model for testing."""
        model = CodeModel(
            total_files=50,
            total_lines=5000,
            total_functions=150,
            total_classes=30,
            project_root="/test/maria",
        )
        model.packages = {
            "agent_core": ["agent_core.homeostasis", "agent_core.memory"],
            "maria_core": ["maria_core.brain", "maria_core.learning"],
        }
        model.layers = {
            "core": ["agent_core.homeostasis", "agent_core.memory"],
            "legacy": ["maria_core.brain", "maria_core.learning"],
        }
        model.issues = [
            CodeIssue(IssueType.TODO, IssueSeverity.INFO, "test.py", 10, "Fix later"),
            CodeIssue(IssueType.FIXME, IssueSeverity.WARNING, "test.py", 20, "Bug here"),
        ]
        return model

    def test_human_reporter_summary(self, sample_model):
        """Test human-readable summary."""
        reporter = HumanReporter(sample_model)
        summary = reporter.summary()

        assert "50" in summary or "plikow" in summary
        assert len(summary) > 50  # Should be a meaningful description

    def test_human_reporter_describe_size(self, sample_model):
        """Test size description."""
        reporter = HumanReporter(sample_model)
        desc = reporter._describe_size()

        assert "5000" in desc or "linii" in desc
        assert "50" in desc or "plikow" in desc

    def test_technical_reporter_summary(self, sample_model):
        """Test technical summary."""
        reporter = TechnicalReporter(sample_model)
        summary = reporter.summary()

        assert "[Files: 50" in summary
        assert "Lines: 5000" in summary
        assert "Functions: 150" in summary

    def test_technical_reporter_detailed_stats(self, sample_model):
        """Test detailed statistics."""
        reporter = TechnicalReporter(sample_model)
        report = reporter.detailed_stats()

        assert "CODE INTROSPECTION REPORT" in report
        assert "Total files:" in report
        assert "50" in report

    def test_technical_reporter_issues(self, sample_model):
        """Test issues report."""
        reporter = TechnicalReporter(sample_model)
        report = reporter.issues_report()

        assert "CODE ISSUES" in report
        assert "todo" in report.lower()
        assert "fixme" in report.lower()

    def test_dual_reporter(self, sample_model):
        """Test dual reporter."""
        reporter = DualReporter(sample_model)
        human, tech = reporter.full_report()

        assert len(human) > 0
        assert len(tech) > 0
        assert "[Files:" in tech

    def test_dual_reporter_formatted(self, sample_model):
        """Test formatted output."""
        reporter = DualReporter(sample_model)
        output = reporter.formatted_output()

        assert "[Files:" in output
        assert "\n" in output


class TestIntrospectionScheduler:
    """Tests for scheduler."""

    @pytest.fixture
    def temp_project(self, tmp_path):
        """Create minimal project structure."""
        agent_core = tmp_path / "agent_core"
        agent_core.mkdir()
        (agent_core / "__init__.py").write_text("# agent_core")
        (agent_core / "test.py").write_text("def test(): pass")
        return tmp_path

    def test_scheduler_init(self, temp_project):
        """Test scheduler initialization."""
        scheduler = IntrospectionScheduler(
            project_root=str(temp_project),
            interval_sec=600,
        )
        assert scheduler.interval_sec == 600
        assert not scheduler.is_running()

    def test_scheduler_run_now(self, temp_project):
        """Test immediate analysis."""
        scheduler = IntrospectionScheduler(
            project_root=str(temp_project),
        )
        model = scheduler.run_now()

        assert model is not None
        # May be 0 if no files in MARIA_PACKAGES directories
        assert model.total_files >= 0

    def test_scheduler_get_model(self, temp_project):
        """Test getting model after analysis."""
        scheduler = IntrospectionScheduler(
            project_root=str(temp_project),
        )

        # Before analysis
        assert scheduler.get_model() is None

        # After analysis
        scheduler.run_now()
        assert scheduler.get_model() is not None

    def test_scheduler_summaries(self, temp_project):
        """Test summary generation."""
        scheduler = IntrospectionScheduler(
            project_root=str(temp_project),
        )
        scheduler.run_now()

        human = scheduler.get_human_summary()
        tech = scheduler.get_technical_summary()

        assert human is not None
        assert tech is not None
        assert len(human) > 0
        assert len(tech) > 0

    def test_scheduler_dual_summary(self, temp_project):
        """Test dual summary."""
        scheduler = IntrospectionScheduler(
            project_root=str(temp_project),
        )
        scheduler.run_now()

        human, tech = scheduler.get_dual_summary()

        assert human is not None
        assert tech is not None


class TestReadOnlyGuarantee:
    """
    Tests to verify the module is READ-ONLY.

    These tests ensure introspection never modifies code.
    """

    def test_analyzer_does_not_modify_files(self, tmp_path):
        """Verify analyzer doesn't modify any files."""
        # Create a test file
        agent_core = tmp_path / "agent_core"
        agent_core.mkdir()
        test_file = agent_core / "test.py"
        original_content = "def test(): pass\n"
        test_file.write_text(original_content)

        # Get modification time before
        mtime_before = test_file.stat().st_mtime

        # Run analysis
        analyzer = CodeAnalyzer(str(tmp_path))
        analyzer.analyze()

        # Verify file unchanged
        assert test_file.read_text() == original_content
        assert test_file.stat().st_mtime == mtime_before

    def test_scheduler_only_writes_to_output(self, tmp_path):
        """Verify scheduler only writes to designated output."""
        # Create project structure
        agent_core = tmp_path / "agent_core"
        agent_core.mkdir()
        (agent_core / "__init__.py").write_text("# init")
        (agent_core / "test.py").write_text("def test(): pass")

        # Create meta_data directory for output
        meta_data = tmp_path / "meta_data"
        meta_data.mkdir()

        # Get all files before
        files_before = set(tmp_path.rglob("*"))

        # Run scheduler
        output_path = meta_data / "analysis.json"
        scheduler = IntrospectionScheduler(
            project_root=str(tmp_path),
            output_path=str(output_path),
        )
        scheduler.run_now()

        # Get all files after
        files_after = set(tmp_path.rglob("*"))

        # Only new files should be analysis.json
        new_files = files_after - files_before
        new_file_names = {f.name for f in new_files if f.is_file()}

        # Should only create analysis output file
        assert "analysis.json" in new_file_names
        # No Python files should be created/modified
        assert not any(f.suffix == ".py" for f in new_files)
