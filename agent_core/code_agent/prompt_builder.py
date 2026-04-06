"""
CodePromptBuilder - constructs prompts with Maria's architecture context.

Gathers introspection data, existing module patterns, and project conventions
to give LLMs full context for generating code that fits Maria's architecture.
"""

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent_core.code_agent.models import GeneratedFile, PlannedFile

logger = logging.getLogger(__name__)

# Project root (one level up from agent_core/)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


_ARCHITECTURE_TEMPLATE = """\
You are writing code for M.A.R.I.A. (Meta Analysis Recalibration Intelligence Architecture),
an autonomous AI agent written in Python 3.8+.

PROJECT STRUCTURE:
{directory_tree}

KEY PATTERNS:
- New subsystems go in agent_core/<name>/ (e.g., agent_core/voice/)
- Each subsystem has __init__.py with public exports
- Modules inherit from MariaModule (agent_core/registry/base_module.py)
- Shared state via SharedContext dataclass (agent_core/registry/shared_context.py)
- Tests in agent_core/tests/test_<name>.py using pytest, all external calls mocked

MODULE REGISTRATION PATTERN:
```python
from agent_core.registry import MariaModule, CommandInfo

class MyModule(MariaModule):
    name = "mymodule"
    description = "What it does"

    def init(self, ctx) -> bool:
        self.ctx = ctx
        return True

    def get_commands(self):
        return [CommandInfo("/mycommand", self._handle, "  /mycommand - help text", "[CATEGORY]")]

    def cleanup(self):
        pass
```

SHARED CONTEXT FIELDS (available via ctx.*):
brain, homeostasis_core, identity_store, consciousness, perception_buffer,
sandbox_manager, goal_store, planner_core, world_model, autonomy_policy,
deliberation, meta_cognition, action_safety, experiment_system,
model_scheduler, openclaw_client, self_analysis, creative_module,
telegram_bridge, semantic_search, trace_store, memory_query,
vision_cortex, capability_router, product_shell, code_agent

CONVENTIONS:
- Docstrings in English
- Comments may be in Polish
- Type hints preferred
- NO emoji in code (ADR-005)
- Frozen dataclasses for immutable data
- JSONL for persistence (append-only, MERGE semantics)
- Threading (not asyncio) per ADR-002
"""

_DESIGN_PROMPT = """\
{architecture_context}

TASK: {task_description}

Design the implementation. For each file to create, specify:
1. path (relative to project root)
2. purpose (what it does)
3. complexity (low/medium/high)
4. dependencies (other files it imports from)
5. is_test (true if test file)

Output ONLY a JSON array of objects with keys: path, purpose, complexity, dependencies, is_test.
No explanation, no markdown fences, just the JSON array.
"""

_GENERATE_PROMPT = """\
{architecture_context}

FILE TO WRITE: {file_path}
PURPOSE: {purpose}
COMPLEXITY: {complexity}

{dependency_context}

{existing_code_context}

Write the complete Python file. Include docstring, imports, classes/functions.
Follow Maria's conventions (type hints, frozen dataclasses, no emoji).
Output ONLY the Python code, no markdown fences, no explanation.
"""

_FIX_PROMPT = """\
The following Python file has test failures. Fix the code.

FILE: {file_path}

CURRENT CODE:
```python
{current_code}
```

TEST OUTPUT (errors):
```
{test_output}
```

SPECIFIC ERRORS:
{error_lines}

Write the complete fixed file. Output ONLY the Python code, no markdown fences.
"""

_REVIEW_PROMPT = """\
Review the following files for correctness, style, and potential issues.
These files are part of M.A.R.I.A., an autonomous AI agent.

{files_summary}

Check for:
1. Import errors or missing dependencies
2. Type hint issues
3. Potential runtime errors
4. Convention violations (no emoji, English docstrings)
5. Security issues (command injection, path traversal)

Output a brief review (max 10 lines). Start with PASS or FAIL.
"""


class CodePromptBuilder:
    """Builds prompts with Maria's architecture context for code generation."""

    def __init__(self, project_root: Optional[str] = None):
        self._project_root = Path(project_root) if project_root else _PROJECT_ROOT
        self._cached_context: Optional[str] = None

    def gather_architecture_context(self) -> str:
        """Build architecture context string from introspection data.

        Reads code_self_model.json for structure, plus key pattern files.
        Cached after first call (architecture doesn't change mid-session).
        """
        if self._cached_context is not None:
            return self._cached_context

        # Build directory tree from introspection
        tree = self._get_directory_tree()

        context = _ARCHITECTURE_TEMPLATE.format(directory_tree=tree)
        self._cached_context = context
        return context

    def build_design_prompt(self, task: str) -> str:
        """Build prompt for LLM to design file plan."""
        ctx = self.gather_architecture_context()
        return _DESIGN_PROMPT.format(
            architecture_context=ctx,
            task_description=task,
        )

    def build_generate_prompt(
        self,
        file_plan: PlannedFile,
        existing_code: Optional[str] = None,
    ) -> str:
        """Build prompt for LLM to generate one file."""
        ctx = self.gather_architecture_context()

        # Build dependency context
        dep_ctx = ""
        if file_plan.dependencies:
            dep_ctx = f"DEPENDS ON: {', '.join(file_plan.dependencies)}"

        # Include existing code if modifying
        existing_ctx = ""
        if existing_code:
            existing_ctx = f"EXISTING CODE (modify/extend):\n```python\n{existing_code}\n```"

        return _GENERATE_PROMPT.format(
            architecture_context=ctx,
            file_path=file_plan.path,
            purpose=file_plan.purpose,
            complexity=file_plan.complexity,
            dependency_context=dep_ctx,
            existing_code_context=existing_ctx,
        )

    def build_fix_prompt(
        self,
        file_path: str,
        current_code: str,
        test_output: str,
        error_lines: str = "",
    ) -> str:
        """Build prompt for LLM to fix code based on test failures."""
        return _FIX_PROMPT.format(
            file_path=file_path,
            current_code=current_code,
            test_output=test_output[-3000:],  # Truncate long output
            error_lines=error_lines[:1500],
        )

    def build_review_prompt(self, files: List[GeneratedFile]) -> str:
        """Build prompt for final code review."""
        summaries = []
        for f in files:
            # Include first 50 lines of each file
            lines = f.content.split("\n")
            preview = "\n".join(lines[:50])
            if len(lines) > 50:
                preview += f"\n... ({len(lines) - 50} more lines)"
            summaries.append(f"--- {f.path} ---\n{preview}\n")

        return _REVIEW_PROMPT.format(
            files_summary="\n".join(summaries),
        )

    def _get_directory_tree(self) -> str:
        """Get directory tree from introspection or filesystem."""
        # Try code_self_model.json first
        model_path = self._project_root / "meta_data" / "code_self_model.json"
        if model_path.exists():
            try:
                with open(model_path, "r", encoding="utf-8") as f:
                    model = json.load(f)
                stats = model.get("statistics", {})
                packages = model.get("packages", {})
                lines = [
                    f"Total: {stats.get('files', '?')} files, "
                    f"{stats.get('lines', '?')} lines, "
                    f"{stats.get('functions', '?')} functions, "
                    f"{stats.get('classes', '?')} classes",
                    "",
                ]
                for pkg_name, modules in sorted(packages.items()):
                    lines.append(f"{pkg_name}/")
                    if isinstance(modules, list):
                        for mod in sorted(modules)[:15]:
                            name = mod if isinstance(mod, str) else mod.get("name", str(mod))
                            lines.append(f"  {name}")
                        if len(modules) > 15:
                            lines.append(f"  ... ({len(modules) - 15} more)")
                return "\n".join(lines)
            except Exception as e:
                logger.debug(f"Could not read code_self_model.json: {e}")

        # Fallback: list agent_core/ directories
        agent_core = self._project_root / "agent_core"
        if agent_core.exists():
            dirs = sorted(d.name for d in agent_core.iterdir()
                          if d.is_dir() and not d.name.startswith("__"))
            return "agent_core/\n" + "\n".join(f"  {d}/" for d in dirs)

        return "(architecture context unavailable)"

    @staticmethod
    def parse_file_plan(response: str) -> List[PlannedFile]:
        """Parse LLM response into list of PlannedFile.

        Expects JSON array. Handles markdown fences and extra text gracefully.
        """
        # Strip markdown fences
        text = response.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            # Remove first and last fence lines
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines).strip()

        # Find JSON array
        start = text.find("[")
        end = text.rfind("]")
        if start == -1 or end == -1:
            logger.warning("Could not find JSON array in design response")
            return []

        try:
            data = json.loads(text[start:end + 1])
        except json.JSONDecodeError as e:
            logger.warning(f"Could not parse design JSON: {e}")
            return []

        files = []
        for item in data:
            if not isinstance(item, dict) or "path" not in item:
                continue
            files.append(PlannedFile(
                path=item["path"],
                purpose=item.get("purpose", ""),
                complexity=item.get("complexity", "medium"),
                dependencies=tuple(item.get("dependencies", [])),
                is_test=item.get("is_test", False),
            ))
        return files

    @staticmethod
    def extract_code(response: str) -> str:
        """Extract Python code from LLM response.

        Strips markdown fences and surrounding text.
        """
        text = response.strip()

        # If wrapped in ```python ... ```
        if "```python" in text:
            start = text.find("```python") + len("```python")
            end = text.find("```", start)
            if end != -1:
                return text[start:end].strip()

        # If wrapped in ``` ... ```
        if text.startswith("```") and text.endswith("```"):
            lines = text.split("\n")
            return "\n".join(lines[1:-1]).strip()

        # Already clean code
        return text
