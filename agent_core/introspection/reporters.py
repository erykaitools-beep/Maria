"""
Reporters for Maria's code introspection.

Provides two output formats:
- HumanReporter: Natural language for Maria's self-expression
- TechnicalReporter: Lab data format with details

Following the dual-communication pattern from CONSCIOUSNESS_SPEC.md
"""

from typing import Optional
from .code_model import CodeModel, IssueSeverity


class HumanReporter:
    """
    Generates natural language descriptions of Maria's code.

    This allows Maria to talk about herself in first person,
    as specified in CONSCIOUSNESS_SPEC.md.
    """

    def __init__(self, model: CodeModel):
        self.model = model

    def summary(self) -> str:
        """Generate a natural language summary of Maria's architecture."""
        stats = self.model.get_statistics()

        lines = [
            self._describe_size(),
            self._describe_structure(),
            self._describe_health(),
        ]

        return " ".join(lines)

    def _describe_size(self) -> str:
        """Describe Maria's size in human terms."""
        files = self.model.total_files
        lines = self.model.total_lines
        funcs = self.model.total_functions
        classes = self.model.total_classes

        # Size perception
        if lines < 5000:
            size_feel = "jestem jeszcze calkiem mala"
        elif lines < 15000:
            size_feel = "mam juz sporo kodu"
        else:
            size_feel = "jestem calkiem duza"

        return (
            f"Skladam sie z {files} plikow i {lines} linii kodu - {size_feel}. "
            f"Mam {funcs} funkcji i {classes} klas."
        )

    def _describe_structure(self) -> str:
        """Describe Maria's structure in human terms."""
        layers = self.model.layers
        packages = self.model.packages

        if not layers:
            return "Nie mam jeszcze wyraznie okreslonych warstw."

        layer_names = {
            "core": "rdzen (homeostaza, pamiec, LLM)",
            "adapters": "adaptery do starego kodu",
            "legacy": "stary kod maria_core",
            "ui": "interfejs uzytkownika",
            "models": "modele AI",
            "meta": "meta-kontrola i introspekcja",
        }

        parts = []
        for layer, modules in layers.items():
            if modules:
                name = layer_names.get(layer, layer)
                parts.append(f"{name} ({len(modules)} modulow)")

        return f"Moja architektura sklada sie z: {', '.join(parts)}."

    def _describe_health(self) -> str:
        """Describe Maria's code health in human terms."""
        issues = self.model.issues
        if not issues:
            return "Moj kod wyglada czysto, nie widze problemow."

        warnings = sum(1 for i in issues if i.severity == IssueSeverity.WARNING)
        errors = sum(1 for i in issues if i.severity == IssueSeverity.ERROR)
        todos = sum(1 for i in issues if i.issue_type.value == "todo")

        parts = []
        if errors > 0:
            parts.append(f"widze {errors} powaznych problemow")
        if warnings > 0:
            parts.append(f"{warnings} ostrzezen")
        if todos > 0:
            parts.append(f"{todos} rzeczy do zrobienia (TODO)")

        if errors > 0:
            return f"Martwi mnie moj kod: {', '.join(parts)}."
        elif warnings > 3:
            return f"Mam kilka uwag do siebie: {', '.join(parts)}."
        else:
            return f"Ogolnie jestem w dobrej formie, chocia: {', '.join(parts)}."

    def describe_module(self, package: str) -> Optional[str]:
        """Describe a specific module in human terms."""
        module = self.model.get_module(package)
        if not module:
            return None

        desc = f"Modul {package} ma {module.line_count} linii"
        if module.functions:
            desc += f", {len(module.functions)} funkcji"
        if module.classes:
            desc += f" i {len(module.classes)} klas"
        desc += "."

        if module.docstring:
            # Extract first sentence of docstring
            first_sentence = module.docstring.split('.')[0]
            desc += f" Jego cel: {first_sentence}."

        return desc

    def describe_layer(self, layer: str) -> Optional[str]:
        """Describe an architectural layer in human terms."""
        modules = self.model.get_layer_modules(layer)
        if not modules:
            return None

        layer_purposes = {
            "core": "To moje serce - tu zarzadzam homeostaza, pamiecia i LLM.",
            "adapters": "To mosty miedzy nowym a starym kodem.",
            "legacy": "To moj stary kod, wciaz potrzebny ale stopniowo wymieniam go.",
            "ui": "Tak komunikuje sie ze swiatem zewnetrznym.",
            "models": "Tu mieszkaja modele AI, z ktorymi rozmawiam.",
            "meta": "Tu mysle o sobie samej - kontrola i introspekcja.",
        }

        purpose = layer_purposes.get(layer, f"To warstwa {layer}.")
        return f"{purpose} Zawiera {len(modules)} modulow."


class TechnicalReporter:
    """
    Generates technical/lab data format output.

    This provides the [brackets] data alongside Maria's
    human expressions, as per CONSCIOUSNESS_SPEC.md.
    """

    def __init__(self, model: CodeModel):
        self.model = model

    def summary(self) -> str:
        """Generate technical summary in bracket format."""
        stats = self.model.get_statistics()
        issues = stats.get("issues", {})

        return (
            f"[Files: {stats['files']} | Lines: {stats['lines']} | "
            f"Functions: {stats['functions']} | Classes: {stats['classes']} | "
            f"Issues: {issues.get('total', 0)} | "
            f"Analyzed: {stats['timestamp'][:16]}]"
        )

    def detailed_stats(self) -> str:
        """Generate detailed statistics."""
        stats = self.model.get_statistics()
        issues = stats.get("issues", {})

        lines = [
            "=== CODE INTROSPECTION REPORT ===",
            f"Timestamp: {stats['timestamp']}",
            "",
            "--- STATISTICS ---",
            f"Total files:     {stats['files']}",
            f"Total lines:     {stats['lines']}",
            f"Total functions: {stats['functions']}",
            f"Total classes:   {stats['classes']}",
            f"Packages:        {stats['packages']}",
            "",
            "--- ISSUES ---",
            f"Total issues: {issues.get('total', 0)}",
        ]

        by_type = issues.get("by_type", {})
        if by_type:
            lines.append("By type:")
            for itype, count in sorted(by_type.items()):
                lines.append(f"  {itype}: {count}")

        by_severity = issues.get("by_severity", {})
        if by_severity:
            lines.append("By severity:")
            for sev, count in sorted(by_severity.items()):
                lines.append(f"  {sev}: {count}")

        return "\n".join(lines)

    def layers_report(self) -> str:
        """Generate report of architectural layers."""
        lines = ["--- ARCHITECTURAL LAYERS ---"]

        for layer, modules in self.model.layers.items():
            lines.append(f"\n{layer.upper()} ({len(modules)} modules):")
            for mod in sorted(modules)[:10]:  # Limit to 10 per layer
                lines.append(f"  - {mod}")
            if len(modules) > 10:
                lines.append(f"  ... and {len(modules) - 10} more")

        return "\n".join(lines)

    def issues_report(self, max_issues: int = 20) -> str:
        """Generate report of code issues."""
        lines = ["--- CODE ISSUES ---"]

        if not self.model.issues:
            lines.append("No issues found.")
            return "\n".join(lines)

        # Group by severity
        for severity in [IssueSeverity.ERROR, IssueSeverity.WARNING, IssueSeverity.INFO]:
            issues = [i for i in self.model.issues if i.severity == severity]
            if not issues:
                continue

            lines.append(f"\n{severity.value.upper()} ({len(issues)}):")
            for issue in issues[:max_issues // 3]:
                lines.append(
                    f"  [{issue.issue_type.value}] {issue.file_path}:{issue.line_number}"
                )
                lines.append(f"    {issue.message[:80]}")

        return "\n".join(lines)

    def module_report(self, package: str) -> Optional[str]:
        """Generate detailed report for a specific module."""
        module = self.model.get_module(package)
        if not module:
            return None

        lines = [
            f"--- MODULE: {package} ---",
            f"File: {module.relative_path}",
            f"Lines: {module.line_count}",
            f"Has docstring: {module.docstring is not None}",
            "",
            f"Imports: {len(module.imports) + len(module.from_imports)}",
            f"Functions: {module.function_count}",
            f"Classes: {module.class_count}",
        ]

        if module.functions:
            lines.append("\nFunctions:")
            for func in module.functions:
                hint = "typed" if func.has_type_hints else "untyped"
                doc = "documented" if func.docstring else "undocumented"
                lines.append(f"  - {func.name}() [{hint}, {doc}]")

        if module.classes:
            lines.append("\nClasses:")
            for cls in module.classes:
                bases = f"({', '.join(cls.base_classes)})" if cls.base_classes else ""
                lines.append(f"  - {cls.name}{bases} [{cls.method_count} methods]")

        return "\n".join(lines)


class DualReporter:
    """
    Combined reporter that generates both human and technical output.

    Usage:
        reporter = DualReporter(model)
        human, tech = reporter.full_report()
        print(f"Maria: {human}")
        print(f"       {tech}")
    """

    def __init__(self, model: CodeModel):
        self.human = HumanReporter(model)
        self.tech = TechnicalReporter(model)
        self.model = model

    def full_report(self) -> tuple:
        """
        Generate both human and technical summaries.

        Returns:
            (human_text, technical_text) tuple
        """
        return self.human.summary(), self.tech.summary()

    def formatted_output(self) -> str:
        """
        Generate combined output in the dual-format style.

        Returns:
            String with human text followed by technical data in brackets
        """
        human, tech = self.full_report()
        return f"{human}\n       {tech}"
