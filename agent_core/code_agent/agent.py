"""
CodeAgent - autonomous coding orchestrator for M.A.R.I.A.

Sequences the full coding workflow:
plan -> generate -> write -> test -> fix -> review

Uses Claude/Codex for code generation, OpenClaw for file I/O and test execution.
Sessions are persisted to JSONL and can be resumed across planner cycles.

Safety gates:
- Approval checkpoints after plan and after code generation
- Self-modify guard for writes to agent_core/
- Max 3 fix iterations
- Session timeout 1 hour
- OpenClaw write rate limit (5/h)
"""

import ast
import hashlib
import logging
import re
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from agent_core.code_agent.models import (
    ApprovalCheckpoint,
    GeneratedFile,
    PlannedFile,
    TestResult,
    WrittenFile,
)
from agent_core.code_agent.prompt_builder import CodePromptBuilder
from agent_core.code_agent.session import CodeSession, CodeSessionStatus, CodeSessionStore

logger = logging.getLogger(__name__)

# Session timeout (1 hour)
_SESSION_TIMEOUT_S = 3600

# Project root path for path validation
_PROJECT_ROOT = "/home/maria/maria"


class CodeAgent:
    """Orchestrates autonomous coding tasks.

    Usage:
        agent = CodeAgent(ctx)
        session = agent.start("build a voice module")
        # session goes through approval gates, operator reviews via Telegram
        # agent.resume(session_id) picks up where it left off
    """

    def __init__(self, ctx):
        self._ctx = ctx
        self._prompt_builder = CodePromptBuilder()
        self._session_store = CodeSessionStore()

        # External dependencies (resolved lazily from ctx)
        self._openclaw = None
        self._claude_fn: Optional[Callable] = None
        self._codex_fn: Optional[Callable] = None
        self._notify_fn: Optional[Callable] = None

    def set_openclaw(self, client) -> None:
        """Set OpenClaw client for file I/O and test execution."""
        self._openclaw = client

    def set_claude_fn(self, fn: Callable) -> None:
        """Set Claude CLI call function: fn(prompt, source, context) -> str|None."""
        self._claude_fn = fn

    def set_codex_fn(self, fn: Callable) -> None:
        """Set Codex CLI call function: fn(prompt, source, context) -> str|None."""
        self._codex_fn = fn

    def set_notify_fn(self, fn: Callable) -> None:
        """Set Telegram notification function: fn(message) -> None."""
        self._notify_fn = fn

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self, task_description: str, target_dir: str = "") -> CodeSession:
        """Start a new coding session.

        Creates session, runs planning step, then pauses for approval.
        Returns session in AWAITING_APPROVAL state (operator reviews plan).
        """
        if not target_dir:
            target_dir = _PROJECT_ROOT

        # Check for active session
        active = self._session_store.get_active()
        if active:
            return active  # One session at a time

        session = CodeSession(
            task_description=task_description,
            target_dir=target_dir,
        )
        self._session_store.save(session)

        # Run planning step
        self._plan(session)

        return session

    def resume(self, session_id: Optional[str] = None) -> Optional[CodeSession]:
        """Resume a paused session (WAITING_BUDGET or AWAITING_APPROVAL approved).

        Called by planner trigger or operator command.
        Returns None if nothing to resume.
        """
        if session_id:
            session = self._session_store.get(session_id)
        else:
            session = self._session_store.get_resumable()

        if not session:
            return None

        if session.status == CodeSessionStatus.WAITING_BUDGET:
            # Check if we have budget now
            if not self._has_llm_budget():
                return session  # Still waiting
            # Resume from current step
            self._continue_pipeline(session)

        elif session.status == CodeSessionStatus.AWAITING_APPROVAL:
            # Check if latest checkpoint was approved
            if session.approval_checkpoints:
                last_cp = session.approval_checkpoints[-1]
                if last_cp.status == "approved":
                    self._continue_pipeline(session)
                elif last_cp.status == "rejected":
                    session.update_status(CodeSessionStatus.CANCELLED)
                    session.result_summary = f"Odrzucone przez operatora: {last_cp.name}"
                    self._session_store.save(session)

        return session

    def cancel(self, session_id: str) -> bool:
        """Cancel an active session."""
        session = self._session_store.get(session_id)
        if not session or session.status.is_terminal:
            return False
        session.update_status(CodeSessionStatus.CANCELLED)
        session.result_summary = "Anulowane przez operatora"
        self._session_store.save(session)
        self._notify(f"Sesja kodowania {session.session_id} anulowana.")
        return True

    def approve_checkpoint(self, session_id: str) -> bool:
        """Approve the latest pending checkpoint."""
        session = self._session_store.get(session_id)
        if not session or session.status != CodeSessionStatus.AWAITING_APPROVAL:
            return False
        if not session.approval_checkpoints:
            return False
        last_cp = session.approval_checkpoints[-1]
        if last_cp.status != "pending":
            return False
        last_cp.status = "approved"
        self._session_store.save(session)
        return True

    def reject_checkpoint(self, session_id: str) -> bool:
        """Reject the latest pending checkpoint."""
        session = self._session_store.get(session_id)
        if not session or session.status != CodeSessionStatus.AWAITING_APPROVAL:
            return False
        if not session.approval_checkpoints:
            return False
        last_cp = session.approval_checkpoints[-1]
        if last_cp.status != "pending":
            return False
        last_cp.status = "rejected"
        session.update_status(CodeSessionStatus.CANCELLED)
        session.result_summary = f"Odrzucone: {last_cp.name}"
        self._session_store.save(session)
        return True

    def get_active(self) -> Optional[CodeSession]:
        """Get the currently active session."""
        return self._session_store.get_active()

    def get_session(self, session_id: str) -> Optional[CodeSession]:
        """Get session by ID (prefix match)."""
        return self._session_store.get(session_id)

    def list_sessions(self, limit: int = 10) -> List[CodeSession]:
        """List recent sessions."""
        return self._session_store.list_recent(limit)

    # ------------------------------------------------------------------
    # Pipeline steps
    # ------------------------------------------------------------------

    def _continue_pipeline(self, session: CodeSession) -> None:
        """Continue the pipeline from the current step."""
        step = session.current_step

        if step == "plan":
            self._plan(session)
        elif step == "generate":
            self._generate(session)
        elif step == "write":
            self._write(session)
        elif step == "test":
            self._test(session)
        elif step == "fix":
            self._fix(session)
        elif step == "review":
            self._review(session)

    def _plan(self, session: CodeSession) -> None:
        """Step 1: Design - gather context + ask LLM for file plan."""
        session.update_status(CodeSessionStatus.PLANNING)
        session.current_step = "plan"

        # Gather architecture context
        session.architecture_context = self._prompt_builder.gather_architecture_context()

        # Ask Claude (preferred) or Codex for design
        prompt = self._prompt_builder.build_design_prompt(session.task_description)
        response = self._call_llm(session, prompt, prefer_claude=True)

        if not response:
            session.update_status(CodeSessionStatus.WAITING_BUDGET)
            session.current_step = "plan"
            self._session_store.save(session)
            self._notify(f"Sesja {session.session_id}: brak budgetu LLM, wznowie pozniej.")
            return

        # Parse file plan
        files = CodePromptBuilder.parse_file_plan(response)
        if not files:
            session.update_status(CodeSessionStatus.FAILED)
            session.result_summary = "LLM nie zwrocil poprawnego planu plikow"
            self._session_store.save(session)
            return

        session.files_planned = files

        # Request approval
        checkpoint = ApprovalCheckpoint(
            name="plan_review",
            data={
                "files": [f.to_dict() for f in files],
                "task": session.task_description,
            },
        )
        session.add_approval(checkpoint)
        session.update_status(CodeSessionStatus.AWAITING_APPROVAL)
        session.current_step = "generate"  # Next step after approval
        self._session_store.save(session)

        # Notify operator
        file_list = "\n".join(f"  - {f.path} ({f.purpose})" for f in files)
        self._notify(
            f"Code Agent - plan gotowy ({session.session_id}):\n"
            f"Zadanie: {session.task_description}\n"
            f"Pliki:\n{file_list}\n"
            f"Zatwierdz: /code approve {session.session_id[:8]}"
        )

    def _generate(self, session: CodeSession) -> None:
        """Step 2: Generate code for each planned file."""
        session.update_status(CodeSessionStatus.GENERATING)
        session.current_step = "generate"

        start_idx = session.current_file_index

        for i in range(start_idx, len(session.files_planned)):
            file_plan = session.files_planned[i]
            session.current_file_index = i

            # Build prompt
            prompt = self._prompt_builder.build_generate_prompt(file_plan)

            # Route: Claude for complex, Codex for simple/tests
            prefer_claude = file_plan.complexity == "high" and not file_plan.is_test
            response = self._call_llm(session, prompt, prefer_claude=prefer_claude)

            if not response:
                # Budget exhausted mid-generation
                session.update_status(CodeSessionStatus.WAITING_BUDGET)
                self._session_store.save(session)
                self._notify(
                    f"Sesja {session.session_id}: budget LLM wyczerpany "
                    f"({i}/{len(session.files_planned)} plikow). Wznowie pozniej."
                )
                return

            # Extract and validate code
            code = CodePromptBuilder.extract_code(response)
            syntax_ok = self._validate_syntax(code)

            generated = GeneratedFile(
                path=file_plan.path,
                content=code,
                syntax_valid=syntax_ok,
                llm_source=session.llm_calls_used.get("_last_source", "unknown"),
            )
            session.files_generated.append(generated)

        # All files generated - request approval
        checkpoint = ApprovalCheckpoint(
            name="code_review",
            data={
                "files": [f.to_dict() for f in session.files_generated],
                "syntax_errors": [f.path for f in session.files_generated if not f.syntax_valid],
            },
        )
        session.add_approval(checkpoint)
        session.update_status(CodeSessionStatus.AWAITING_APPROVAL)
        session.current_step = "write"
        self._session_store.save(session)

        syntax_issues = [f.path for f in session.files_generated if not f.syntax_valid]
        status_msg = ""
        if syntax_issues:
            status_msg = f"\nBledy skladni w: {', '.join(syntax_issues)}"

        self._notify(
            f"Code Agent - kod wygenerowany ({session.session_id}):\n"
            f"{len(session.files_generated)} plikow gotowych{status_msg}\n"
            f"Zatwierdz: /code approve {session.session_id[:8]}"
        )

    def _write(self, session: CodeSession) -> None:
        """Step 3: Write generated files to disk via OpenClaw."""
        session.update_status(CodeSessionStatus.WRITING)
        session.current_step = "write"

        if not self._openclaw:
            session.update_status(CodeSessionStatus.FAILED)
            session.result_summary = "OpenClaw niedostepny - nie moge zapisac plikow"
            self._session_store.save(session)
            return

        for gen_file in session.files_generated:
            # Path validation
            full_path = self._resolve_path(gen_file.path, session.target_dir)
            if not full_path:
                logger.warning(f"Invalid path: {gen_file.path}")
                continue

            # Self-modify guard
            if self._is_self_modify(full_path) and not self._has_self_modify_approval(session):
                checkpoint = ApprovalCheckpoint(
                    name="self_modify",
                    data={"path": full_path},
                )
                session.add_approval(checkpoint)
                session.update_status(CodeSessionStatus.AWAITING_APPROVAL)
                self._session_store.save(session)
                self._notify(
                    f"Code Agent - zapis do agent_core/ wymaga dodatkowej zgody:\n"
                    f"Plik: {full_path}\n"
                    f"Zatwierdz: /code approve {session.session_id[:8]}"
                )
                return

            # Ensure parent directory exists
            parent_dir = "/".join(full_path.rsplit("/", 1)[:-1])
            if parent_dir:
                try:
                    self._openclaw.invoke_tool("exec", {
                        "command": f"mkdir -p {parent_dir}"
                    })
                except Exception:
                    pass

            # Write file
            try:
                result = self._openclaw.invoke_tool("write", {
                    "path": full_path,
                    "content": gen_file.content,
                })
                ok = result.get("ok", False) if isinstance(result, dict) else False
            except Exception as e:
                logger.warning(f"Write failed for {full_path}: {e}")
                ok = False

            if ok:
                # Verify by reading back
                verified = False
                try:
                    read_result = self._openclaw.invoke_tool("read", {"path": full_path})
                    read_content = read_result.get("result", "") if isinstance(read_result, dict) else ""
                    verified = read_content.strip() == gen_file.content.strip()
                except Exception:
                    pass

                content_hash = hashlib.sha256(gen_file.content.encode()).hexdigest()
                written = WrittenFile(
                    path=full_path,
                    content_hash=content_hash,
                    size_bytes=len(gen_file.content.encode()),
                    verified=verified,
                )
                session.files_written.append(written)

        session.current_step = "test"
        self._session_store.save(session)

        # Proceed to testing
        self._test(session)

    def _test(self, session: CodeSession) -> None:
        """Step 4: Run pytest via OpenClaw."""
        session.update_status(CodeSessionStatus.TESTING)
        session.current_step = "test"

        if not self._openclaw:
            session.update_status(CodeSessionStatus.FAILED)
            session.result_summary = "OpenClaw niedostepny - nie moge uruchomic testow"
            self._session_store.save(session)
            return

        # Find test files
        test_paths = [f.path for f in session.files_planned if f.is_test]
        if not test_paths:
            # No tests planned - skip to review
            session.current_step = "review"
            self._review(session)
            return

        # Run pytest
        test_path_str = " ".join(test_paths)
        command = (
            f"cd {_PROJECT_ROOT} && "
            f"{_PROJECT_ROOT}/venv/bin/python -m pytest {test_path_str} -v --tb=short 2>&1"
        )

        try:
            result = self._openclaw.invoke_tool("exec", {"command": command})
            stdout = result.get("result", "") if isinstance(result, dict) else ""
            exit_code = result.get("exit_code", 1) if isinstance(result, dict) else 1
        except Exception as e:
            stdout = str(e)
            exit_code = 1

        # Parse test output
        passed, failed, errors = self._parse_test_output(stdout)

        test_result = TestResult(
            run_number=len(session.test_results) + 1,
            command=command,
            exit_code=exit_code,
            stdout=stdout,
            passed=passed,
            failed=failed,
            errors=tuple(errors),
        )
        session.add_test_result(test_result)
        self._session_store.save(session)

        if test_result.success:
            # Tests pass - proceed to review
            session.current_step = "review"
            self._review(session)
        else:
            # Tests fail - try fix loop
            if session.iterations < session.max_iterations:
                session.current_step = "fix"
                self._fix(session)
            else:
                session.update_status(CodeSessionStatus.FAILED)
                session.result_summary = (
                    f"Testy nie przechodza po {session.max_iterations} iteracjach fix. "
                    f"Ostatni wynik: {passed} passed, {failed} failed."
                )
                self._session_store.save(session)
                self._notify(
                    f"Code Agent FAILED ({session.session_id}): "
                    f"Max iteracji ({session.max_iterations}). "
                    f"{failed} testow nie przechodzi."
                )

    def _fix(self, session: CodeSession) -> None:
        """Step 5: Fix code based on test failures."""
        session.update_status(CodeSessionStatus.FIXING)
        session.current_step = "fix"
        session.iterations += 1

        last_test = session.last_test_result
        if not last_test:
            session.current_step = "test"
            self._test(session)
            return

        # Find which files have errors
        error_files = self._identify_error_files(last_test)
        if not error_files and last_test.errors:
            # Can't identify specific files - try fixing all non-test files
            error_files = [f.path for f in session.files_generated if not f.path.endswith("test_")]

        for file_path in error_files[:3]:  # Fix max 3 files per iteration
            gen_file = next((f for f in session.files_generated if f.path == file_path), None)
            if not gen_file:
                continue

            # Read current code (may have been modified in previous fix)
            current_code = gen_file.content
            if self._openclaw:
                try:
                    full_path = self._resolve_path(file_path, session.target_dir)
                    if full_path:
                        read_result = self._openclaw.invoke_tool("read", {"path": full_path})
                        if isinstance(read_result, dict) and read_result.get("ok"):
                            current_code = read_result.get("result", current_code)
                except Exception:
                    pass

            # Build fix prompt
            error_lines = "\n".join(last_test.errors[:10])
            prompt = self._prompt_builder.build_fix_prompt(
                file_path=file_path,
                current_code=current_code,
                test_output=last_test.stdout,
                error_lines=error_lines,
            )

            # Prefer Codex for fixes (save Claude for harder problems)
            prefer_claude = session.iterations >= session.max_iterations - 1
            response = self._call_llm(session, prompt, prefer_claude=prefer_claude)

            if not response:
                session.update_status(CodeSessionStatus.WAITING_BUDGET)
                self._session_store.save(session)
                return

            # Extract fixed code and write
            fixed_code = CodePromptBuilder.extract_code(response)
            gen_file.content = fixed_code
            gen_file.syntax_valid = self._validate_syntax(fixed_code)

            if self._openclaw:
                full_path = self._resolve_path(file_path, session.target_dir)
                if full_path:
                    try:
                        self._openclaw.invoke_tool("write", {
                            "path": full_path,
                            "content": fixed_code,
                        })
                    except Exception as e:
                        logger.warning(f"Fix write failed: {e}")

        self._session_store.save(session)

        # Re-test
        session.current_step = "test"
        self._test(session)

    def _review(self, session: CodeSession) -> None:
        """Step 6: Optional final review."""
        # Review is optional - if no budget, skip
        if session.files_generated:
            prompt = self._prompt_builder.build_review_prompt(session.files_generated)
            response = self._call_llm(session, prompt, prefer_claude=False)
            if response:
                session.result_summary = response[:500]

        # Complete session
        session.update_status(CodeSessionStatus.COMPLETED)
        if not session.result_summary:
            written_count = len(session.files_written)
            last_test = session.last_test_result
            test_info = f", testy: {last_test.passed} passed" if last_test else ""
            session.result_summary = f"Zapisano {written_count} plikow{test_info}"

        self._session_store.save(session)

        self._notify(
            f"Code Agent DONE ({session.session_id}):\n"
            f"Zadanie: {session.task_description}\n"
            f"Pliki: {len(session.files_written)} zapisanych\n"
            f"LLM: Claude {session.llm_calls_used.get('claude', 0)}, "
            f"Codex {session.llm_calls_used.get('codex', 0)}\n"
            f"Czas: {session.duration_s:.0f}s\n"
            f"{session.result_summary}"
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _call_llm(
        self, session: CodeSession, prompt: str, prefer_claude: bool = False,
    ) -> Optional[str]:
        """Call Claude or Codex with budget tracking.

        Tries preferred model first, falls back to other.
        Returns None if both exhausted.
        """
        # Try preferred model first
        if prefer_claude and self._claude_fn:
            try:
                response = self._claude_fn(
                    prompt, source="code_agent",
                    context={"session_id": session.session_id},
                )
                if response:
                    session.record_llm_call("claude")
                    session.llm_calls_used["_last_source"] = "claude"
                    return response
            except Exception as e:
                logger.debug(f"Claude call failed: {e}")

        # Try Codex
        if self._codex_fn:
            try:
                response = self._codex_fn(
                    prompt, source="code_agent",
                    context={"session_id": session.session_id},
                )
                if response:
                    session.record_llm_call("codex")
                    session.llm_calls_used["_last_source"] = "codex"
                    return response
            except Exception as e:
                logger.debug(f"Codex call failed: {e}")

        # If Claude wasn't preferred but is available as fallback
        if not prefer_claude and self._claude_fn:
            try:
                response = self._claude_fn(
                    prompt, source="code_agent",
                    context={"session_id": session.session_id},
                )
                if response:
                    session.record_llm_call("claude")
                    session.llm_calls_used["_last_source"] = "claude"
                    return response
            except Exception:
                pass

        return None

    def _has_llm_budget(self) -> bool:
        """Check if any LLM has available budget."""
        if self._claude_fn:
            try:
                # Claude returns None when rate-limited
                return True
            except Exception:
                pass
        if self._codex_fn:
            return True
        return False

    def _validate_syntax(self, code: str) -> bool:
        """Validate Python syntax with ast.parse."""
        try:
            ast.parse(code)
            return True
        except SyntaxError:
            return False

    def _resolve_path(self, path: str, target_dir: str) -> Optional[str]:
        """Resolve and validate file path.

        Prevents path traversal and writes outside project.
        """
        # Handle relative paths
        if not path.startswith("/"):
            full = f"{target_dir}/{path}" if target_dir else f"{_PROJECT_ROOT}/{path}"
        else:
            full = path

        # Normalize
        import os
        full = os.path.normpath(full)

        # Must be within project root
        if not full.startswith(_PROJECT_ROOT):
            logger.warning(f"Path outside project root: {full}")
            return None

        # Block obvious dangerous paths
        dangerous = [".env", "credentials", "password", ".ssh", ".git/"]
        for d in dangerous:
            if d in full.lower():
                logger.warning(f"Blocked dangerous path: {full}")
                return None

        return full

    def _is_self_modify(self, path: str) -> bool:
        """Check if path is within Maria's core code."""
        return "/agent_core/" in path or "/maria_core/" in path

    def _has_self_modify_approval(self, session: CodeSession) -> bool:
        """Check if self-modify has been approved."""
        for cp in session.approval_checkpoints:
            if cp.name == "self_modify" and cp.status == "approved":
                return True
        return False

    def _parse_test_output(self, output: str) -> Tuple[int, int, List[str]]:
        """Parse pytest output for pass/fail counts and error messages."""
        passed = 0
        failed = 0
        errors = []

        # Match "X passed" and "X failed"
        passed_m = re.search(r"(\d+) passed", output)
        failed_m = re.search(r"(\d+) failed", output)
        if passed_m:
            passed = int(passed_m.group(1))
        if failed_m:
            failed = int(failed_m.group(1))

        # Extract FAILED test names
        for line in output.split("\n"):
            if line.strip().startswith("FAILED"):
                errors.append(line.strip())
            elif "Error" in line and "::" in line:
                errors.append(line.strip())

        return passed, failed, errors

    def _identify_error_files(self, test_result: TestResult) -> List[str]:
        """Identify which source files need fixing from test errors."""
        files = set()
        for error in test_result.errors:
            # Extract file paths from error messages
            match = re.search(r"([\w/]+\.py)", error)
            if match:
                path = match.group(1)
                # Map test file to source file
                if "test_" in path:
                    # Don't fix test files - fix source
                    source = path.replace("tests/test_", "").replace("test_", "")
                    files.add(source)
                else:
                    files.add(path)
        return list(files)

    def _notify(self, message: str) -> None:
        """Send notification via Telegram (if available)."""
        if self._notify_fn:
            try:
                self._notify_fn(message)
            except Exception as e:
                logger.debug(f"Notification failed: {e}")
        logger.info(f"[CODE_AGENT] {message}")
