"""ClaudeClient CLI flags guard (audyt 2026-06-12, zrewidowany 2026-06-22).

--dangerously-skip-permissions on the live repo gave anyone who reached
.ask() (webui /api/tasks behind a 6-digit PIN, telegram) an agent with
arbitrary exec/write. The 2026-06-12 fix used --tools "" (ALL tools off) -- but
that left /claude blind: it could not read a file, so it confabulated (wrong
heading invented, verified live 2026-06-22). The revision runs READ-ONLY tools
(Read,Grep,Glob): /claude can analyse code again, but still NO exec/write on the
live repo. This guard pins both halves: read tools present, write/exec absent,
and no permission bypass.
"""

from unittest.mock import MagicMock, patch

from agent_core.llm.claude_client import ClaudeClient

# Tools that must NEVER be enabled for this backend (exec / write on live repo).
_FORBIDDEN_TOOLS = ("Bash", "Edit", "Write", "MultiEdit", "NotebookEdit")


class TestClaudeCliFlags:
    def _captured_cmd(self):
        client = ClaudeClient(timeout_s=5)
        captured = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            result = MagicMock()
            result.returncode = 0
            result.stdout = "ok"
            result.stderr = ""
            return result

        with patch("agent_core.llm.claude_client.subprocess.run", fake_run):
            client._invoke("test prompt")
        return captured["cmd"]

    def test_no_dangerous_permission_bypass(self):
        cmd = self._captured_cmd()
        assert "--dangerously-skip-permissions" not in cmd
        assert "--allow-dangerously-skip-permissions" not in cmd

    def test_tools_are_read_only(self):
        cmd = self._captured_cmd()
        i = cmd.index("--tools")
        tools = cmd[i + 1]
        # Read-only set: read/search tools present...
        assert "Read" in tools
        # ...and NO exec/write tool anywhere in the spec.
        for forbidden in _FORBIDDEN_TOOLS:
            assert forbidden not in tools, f"{forbidden} must not be enabled"

    def test_output_format_text(self):
        cmd = self._captured_cmd()
        i = cmd.index("--output-format")
        assert cmd[i + 1] == "text"
