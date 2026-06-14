"""ClaudeClient CLI flags guard (audyt 2026-06-12).

--dangerously-skip-permissions on the live repo gave anyone who reached
.ask() (webui /api/tasks behind a 6-digit PIN, telegram) an agent with
arbitrary exec/write. All .ask() consumers (K12, code_agent, tasks) need
PLAIN TEXT -- the CLI runs with --tools "" (all tools disabled), verified
live 2026-06-12 (claude --tools "" -p ... -> exit 0).
"""

from unittest.mock import MagicMock, patch

from agent_core.llm.claude_client import ClaudeClient


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

    def test_all_tools_disabled(self):
        cmd = self._captured_cmd()
        i = cmd.index("--tools")
        assert cmd[i + 1] == ""
